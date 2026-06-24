from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from typing import Any

from prism_collector.models import SourceItem

COMMENT_COLLECTION_THRESHOLD = 100
MAX_COMMENT_THREADS = 100


def collect_youtube(topic: dict[str, Any], limit: int = 10) -> list[SourceItem]:
    api_key = os.getenv("YOUTUBE_API_KEY")
    if not api_key:
        return []

    topic_id = str(topic["id"])
    query_text = topic.get("youtube", {}).get("query") or " ".join(topic.get("keywords", []))
    query = urllib.parse.urlencode(
        {
            "part": "snippet",
            "q": query_text,
            "type": "video",
            "order": "relevance",
            "maxResults": str(limit),
            "key": api_key,
        }
    )
    url = f"https://www.googleapis.com/youtube/v3/search?{query}"

    try:
        payload = _get_json(url)
    except Exception as exc:
        print(f"Skipping YouTube collection: {exc}", file=sys.stderr)
        return []

    items: list[SourceItem] = []
    video_ids = [
        entry.get("id", {}).get("videoId")
        for entry in payload.get("items", [])
        if entry.get("id", {}).get("videoId")
    ]
    details_by_id = _fetch_video_details(video_ids, api_key=api_key)

    for entry in payload.get("items", []):
        video_id = entry.get("id", {}).get("videoId")
        snippet = entry.get("snippet", {})
        if not video_id:
            continue
        details = details_by_id.get(video_id, {})
        detail_snippet = details.get("snippet", {})
        statistics = details.get("statistics", {})
        comment_count = _int_or_none(statistics.get("commentCount"))
        transcript = _fetch_transcript(video_id)
        transcript_available = bool(transcript)
        description = detail_snippet.get("description") or snippet.get("description") or None
        # Keep the video even when the transcript is blocked/unavailable: store the
        # description as the raw_text fallback so the item still shows up downstream,
        # and flag it so a later run can backfill the transcript once a proxy works.
        if transcript_available:
            raw_text = transcript
            raw_text_kind = "transcript"
        else:
            raw_text = description
            raw_text_kind = "description"
            print(
                f"YouTube video {video_id}: transcript unavailable, storing metadata only",
                file=sys.stderr,
            )
        comments = (
            _fetch_video_comments(video_id, api_key=api_key, limit=MAX_COMMENT_THREADS)
            if _should_collect_comments(comment_count)
            else []
        )
        items.append(
            SourceItem(
                source="youtube",
                topic_id=topic_id,
                external_id=video_id,
                url=f"https://www.youtube.com/watch?v={video_id}",
                title=str(detail_snippet.get("title") or snippet.get("title", "")),
                author=detail_snippet.get("channelTitle") or snippet.get("channelTitle"),
                community=detail_snippet.get("channelTitle") or snippet.get("channelTitle"),
                published_at=detail_snippet.get("publishedAt") or snippet.get("publishedAt"),
                comment_count=comment_count,
                raw_text=raw_text,
                metadata={
                    "channel_id": detail_snippet.get("channelId") or snippet.get("channelId"),
                    "thumbnail": _thumbnail_url(detail_snippet or snippet),
                    "description": description,
                    "raw_text_kind": raw_text_kind,
                    "transcript_char_count": len(transcript) if transcript_available else 0,
                    "view_count": _int_or_none(statistics.get("viewCount")),
                    "like_count": _int_or_none(statistics.get("likeCount")),
                    "transcript_available": transcript_available,
                    "transcript_source": "youtube-transcript-api" if transcript_available else None,
                    "comments_collected": len(comments),
                    "comment_collection_threshold": COMMENT_COLLECTION_THRESHOLD,
                    "youtube_comments": comments,
                },
            )
        )
    return items


def _fetch_video_details(video_ids: list[str], *, api_key: str) -> dict[str, dict[str, Any]]:
    if not video_ids:
        return {}
    query = urllib.parse.urlencode(
        {
            "part": "snippet,statistics",
            "id": ",".join(video_ids),
            "key": api_key,
        }
    )
    url = f"https://www.googleapis.com/youtube/v3/videos?{query}"
    try:
        payload = _get_json(url)
    except Exception as exc:
        print(f"Skipping YouTube video details: {exc}", file=sys.stderr)
        return {}
    return {str(item.get("id")): item for item in payload.get("items", []) if item.get("id")}


_NO_PROXY_WARNING_EMITTED = False


def _fetch_transcript(video_id: str) -> str | None:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except Exception as exc:
        print(f"Transcript dependency unavailable for {video_id}: {exc}", file=sys.stderr)
        return None

    proxy_config = _transcript_proxy_config()
    if proxy_config is None:
        _warn_no_proxy_once()

    try:
        api = (
            YouTubeTranscriptApi(proxy_config=proxy_config)
            if proxy_config is not None
            else YouTubeTranscriptApi()
        )
    except TypeError as exc:
        # youtube-transcript-api < 1.0 does not support proxy_config / the
        # instance-based interface. Proxies cannot be applied on those versions.
        print(
            f"Skipping transcript for {video_id}: installed youtube-transcript-api is too old "
            f"for proxy support; pin youtube-transcript-api>=1.0.3 ({exc})",
            file=sys.stderr,
        )
        return None

    # List the actual transcript tracks so we can pick the most complete one.
    # A naive fetch(languages=["en"]) prefers a manually-created caption, which is
    # often partial (intro-only or an unfinished community contribution). We instead
    # fetch every candidate track and keep the longest, so the full video is captured.
    try:
        transcript_list = api.list(video_id)
    except Exception as list_exc:
        try:
            return _transcript_to_text(api.fetch(video_id, languages=["en"]))
        except Exception as fetch_exc:
            print(
                _describe_transcript_failure(video_id, list_exc, fetch_exc, proxy_config),
                file=sys.stderr,
            )
            return None

    candidates = _transcript_candidates(transcript_list)
    best_text: str | None = None
    errors: list[Exception] = []
    for transcript in candidates:
        try:
            text = _transcript_to_text(transcript.fetch())
        except Exception as exc:
            errors.append(exc)
            continue
        if text and (best_text is None or len(text) > len(best_text)):
            best_text = text

    if best_text is None:
        primary = errors[0] if errors else RuntimeError("no transcripts available")
        secondary = errors[-1] if errors else primary
        print(
            _describe_transcript_failure(video_id, primary, secondary, proxy_config),
            file=sys.stderr,
        )
        return None

    return best_text


def _transcript_candidates(transcript_list: Any) -> list[Any]:
    """Ordered transcript tracks to try, maximizing transcript completeness.

    Prefers English tracks (both manual and auto-generated) so we can compare
    their lengths and keep the longest. Falls back to a generated track in any
    language, then any available track.
    """
    try:
        tracks = list(transcript_list)
    except TypeError:
        return []

    english = [
        track
        for track in tracks
        if str(getattr(track, "language_code", "") or "").lower().startswith("en")
    ]
    if english:
        return english

    generated = [track for track in tracks if getattr(track, "is_generated", False)]
    if generated:
        return generated
    return tracks[:1]


def _warn_no_proxy_once() -> None:
    global _NO_PROXY_WARNING_EMITTED
    if _NO_PROXY_WARNING_EMITTED:
        return
    _NO_PROXY_WARNING_EMITTED = True
    print(
        "No transcript proxy configured. YouTube blocks transcript requests from cloud IPs "
        "(GitHub Actions, AWS, GCP, Azure). Set Webshare residential proxy secrets "
        "(YOUTUBE_TRANSCRIPT_WEBSHARE_USERNAME / YOUTUBE_TRANSCRIPT_WEBSHARE_PASSWORD) or a "
        "generic proxy (YOUTUBE_TRANSCRIPT_PROXY_HTTP_URL / YOUTUBE_TRANSCRIPT_PROXY_HTTPS_URL).",
        file=sys.stderr,
    )


def _describe_transcript_failure(
    video_id: str,
    primary_exc: Exception,
    secondary_exc: Exception,
    proxy_config: Any | None,
) -> str:
    blocked_errors = {"RequestBlocked", "IpBlocked"}
    exc_names = {type(primary_exc).__name__, type(secondary_exc).__name__}
    if exc_names & blocked_errors:
        if proxy_config is None:
            return (
                f"Transcript for {video_id} blocked by YouTube (cloud IP). No proxy is "
                "configured. Set Webshare residential proxy secrets "
                "(YOUTUBE_TRANSCRIPT_WEBSHARE_USERNAME / YOUTUBE_TRANSCRIPT_WEBSHARE_PASSWORD)."
            )
        return (
            f"Transcript for {video_id} blocked by YouTube even through the configured proxy. "
            "Confirm the proxy is a Webshare 'Residential' (rotating) package - NOT 'Proxy Server' "
            "or 'Static Residential' - and that the credentials are current."
        )
    return f"Skipping transcript for {video_id}: {primary_exc}"


def _transcript_proxy_config() -> Any | None:
    webshare_username = os.getenv("YOUTUBE_TRANSCRIPT_WEBSHARE_USERNAME")
    webshare_password = os.getenv("YOUTUBE_TRANSCRIPT_WEBSHARE_PASSWORD")
    if webshare_username and webshare_password:
        try:
            from youtube_transcript_api.proxies import WebshareProxyConfig
        except Exception as exc:
            print(f"Webshare proxy config unavailable: {exc}", file=sys.stderr)
            return None
        locations = [
            item.strip()
            for item in os.getenv("YOUTUBE_TRANSCRIPT_WEBSHARE_LOCATIONS", "").split(",")
            if item.strip()
        ]
        kwargs: dict[str, Any] = {
            "proxy_username": webshare_username,
            "proxy_password": webshare_password,
        }
        if locations:
            kwargs["filter_ip_locations"] = locations
        # Newer releases let the client transparently retry on a fresh rotating IP
        # when a request is blocked. Only pass it if the installed version supports it.
        if _supports_kwarg(WebshareProxyConfig, "retries_when_blocked"):
            kwargs["retries_when_blocked"] = 15
        return WebshareProxyConfig(**kwargs)

    http_url = os.getenv("YOUTUBE_TRANSCRIPT_PROXY_HTTP_URL")
    https_url = os.getenv("YOUTUBE_TRANSCRIPT_PROXY_HTTPS_URL")
    if http_url or https_url:
        try:
            from youtube_transcript_api.proxies import GenericProxyConfig
        except Exception as exc:
            print(f"Generic proxy config unavailable: {exc}", file=sys.stderr)
            return None
        return GenericProxyConfig(http_url=http_url, https_url=https_url)

    return None


def _supports_kwarg(target: Any, name: str) -> bool:
    try:
        import inspect

        return name in inspect.signature(target).parameters
    except (TypeError, ValueError):
        return False


def _transcript_to_text(transcript: Any) -> str | None:
    parts = [_transcript_segment_text(segment) for segment in transcript]
    text = " ".join(part for part in parts if part)
    return text or None


def _transcript_segment_text(segment: Any) -> str:
    if isinstance(segment, dict):
        return str(segment.get("text", "")).strip()
    return str(getattr(segment, "text", "")).strip()


def _fetch_video_comments(video_id: str, *, api_key: str, limit: int) -> list[dict[str, Any]]:
    comments: list[dict[str, Any]] = []
    page_token: str | None = None

    while len(comments) < limit:
        params = {
            "part": "snippet,replies",
            "videoId": video_id,
            "maxResults": str(min(100, limit - len(comments))),
            "order": "relevance",
            "textFormat": "plainText",
            "key": api_key,
        }
        if page_token:
            params["pageToken"] = page_token
        url = f"https://www.googleapis.com/youtube/v3/commentThreads?{urllib.parse.urlencode(params)}"
        try:
            payload = _get_json(url)
        except Exception as exc:
            print(f"Skipping comments for {video_id}: {exc}", file=sys.stderr)
            return comments

        for item in payload.get("items", []):
            comment = _comment_thread_to_dict(item)
            if comment:
                comments.append(comment)
        page_token = payload.get("nextPageToken")
        if not page_token:
            break

    return comments


def _comment_thread_to_dict(item: dict[str, Any]) -> dict[str, Any] | None:
    snippet = item.get("snippet", {})
    top = snippet.get("topLevelComment", {}).get("snippet", {})
    text = top.get("textDisplay") or top.get("textOriginal")
    if not text:
        return None
    return {
        "id": item.get("id"),
        "author": top.get("authorDisplayName"),
        "text": text,
        "like_count": _int_or_none(top.get("likeCount")),
        "published_at": top.get("publishedAt"),
        "updated_at": top.get("updatedAt"),
        "reply_count": _int_or_none(snippet.get("totalReplyCount")),
    }


def _should_collect_comments(comment_count: int | None) -> bool:
    return comment_count is not None and comment_count > COMMENT_COLLECTION_THRESHOLD


def _get_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _thumbnail_url(snippet: dict[str, Any]) -> str | None:
    thumbnails = snippet.get("thumbnails", {})
    for size in ("high", "medium", "default"):
        url = thumbnails.get(size, {}).get("url")
        if url:
            return str(url)
    return None
