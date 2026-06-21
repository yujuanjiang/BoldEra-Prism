from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from typing import Any

from prism_collector.models import SourceItem


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

    request = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        print(f"Skipping YouTube collection: {exc}", file=sys.stderr)
        return []

    items: list[SourceItem] = []
    for entry in payload.get("items", []):
        video_id = entry.get("id", {}).get("videoId")
        snippet = entry.get("snippet", {})
        if not video_id:
            continue
        items.append(
            SourceItem(
                source="youtube",
                topic_id=topic_id,
                external_id=video_id,
                url=f"https://www.youtube.com/watch?v={video_id}",
                title=str(snippet.get("title", "")),
                author=snippet.get("channelTitle"),
                community=snippet.get("channelTitle"),
                published_at=snippet.get("publishedAt"),
                raw_text=snippet.get("description") or None,
                metadata={
                    "channel_id": snippet.get("channelId"),
                    "thumbnail": _thumbnail_url(snippet),
                },
            )
        )
    return items


def _thumbnail_url(snippet: dict[str, Any]) -> str | None:
    thumbnails = snippet.get("thumbnails", {})
    for size in ("high", "medium", "default"):
        url = thumbnails.get(size, {}).get("url")
        if url:
            return str(url)
    return None
