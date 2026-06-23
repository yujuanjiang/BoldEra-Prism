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
        if not transcript:
            print(f"Skipping YouTube video {video_id}: transcript unavailable", file=sys.stderr)
            continue
        comments = (
            _fetch_video_comments(video_id, api_key=api_key, limit=MAX_COMMENT_THREADS)
            if _should_collect_comments(comment_count)
            else []
        )
        description = detail_snippet.get("description") or snippet.get("description") or None
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
                raw_text=transcript,
                metadata={
                    "channel_id": detail_snippet.get("channelId") or snippet.get("channelId"),
                    "thumbnail": _thumbnail_url(detail_snippet or snippet),
                    "description": description,
                    "raw_text_kind": "transcript",
                    "transcript_char_count": len(transcript),
                    "view_count": _int_or_none(statistics.get("viewCount")),
                    "like_count": _int_or_none(statistics.get("likeCount")),
                    "transcript_available": True,
                    "transcript_source": "youtube-transcript-api",
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


def _fetch_transcript(video_id: str) -> str | None:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except Exception as exc:
        print(f"Transcript dependency unavailable for {video_id}: {exc}", file=sys.stderr)
        return None

    attempts: list[str] = []
    try:
        api = _transcript_api(YouTubeTranscriptApi)
        if hasattr(api, "fetch"):
            attempts.append("instance.fetch(en)")
            transcript = api.fetch(video_id, languages=["en"])
        elif hasattr(YouTubeTranscriptApi, "get_transcript"):
            attempts.append("class.get_transcript(en)")
            transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=["en"])
        elif hasattr(YouTubeTranscriptApi, "list_transcripts"):
            attempts.append("class.list_transcripts.find_transcript(en)")
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
            transcript = transcript_list.find_transcript(["en"]).fetch()
        else:
            raise AttributeError(_transcript_api_error(YouTubeTranscriptApi, api))
    except Exception as first_exc:
        try:
            api = _transcript_api(YouTubeTranscriptApi)
            if hasattr(api, "list"):
                attempts.append("instance.list.find_generated_transcript(en)")
                transcript_list = api.list(video_id)
                transcript = transcript_list.find_generated_transcript(["en"]).fetch()
            elif hasattr(YouTubeTranscriptApi, "get_transcript"):
                attempts.append("class.get_transcript(default)")
                transcript = YouTubeTranscriptApi.get_transcript(video_id)
            elif hasattr(YouTubeTranscriptApi, "list_transcripts"):
                attempts.append("class.list_transcripts.find_generated_transcript(en)")
                transcript = YouTubeTranscriptApi.list_transcripts(video_id).find_generated_transcript(
                    ["en"]
                ).fetch()
            else:
                raise AttributeError(_transcript_api_error(YouTubeTranscriptApi, api))
        except Exception as exc:
            attempted = ", ".join(attempts) or "no compatible methods"
            print(
                f"Skipping transcript for {video_id}: attempted {attempted}; {first_exc}; {exc}",
                file=sys.stderr,
            )
            return None

    return _transcript_to_text(transcript)


def _transcript_api(api_class: Any) -> Any:
    proxy_config = _transcript_proxy_config()
    if proxy_config is not None:
        return api_class(proxy_config=proxy_config)
    return api_class()


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


def _transcript_api_error(api_class: Any, api_instance: Any) -> str:
    class_methods = [
        name
        for name in ("get_transcript", "list_transcripts")
        if hasattr(api_class, name)
    ]
    instance_methods = [name for name in ("fetch", "list") if hasattr(api_instance, name)]
    return (
        "Unsupported youtube-transcript-api interface. "
        f"class methods={class_methods}, instance methods={instance_methods}"
    )


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
