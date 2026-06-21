from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from typing import Any

from prism_collector.models import SourceItem


USER_AGENT = "BoldEra-Prism/0.1 data collector"


def collect_reddit(topic: dict[str, Any], limit: int = 10) -> list[SourceItem]:
    topic_id = str(topic["id"])
    keywords = " OR ".join(topic.get("keywords", []))
    subreddits = topic.get("reddit", {}).get("subreddits", [])
    items: list[SourceItem] = []

    for subreddit in subreddits:
        query = urllib.parse.urlencode(
            {
                "q": keywords,
                "restrict_sr": "on",
                "sort": "relevance",
                "t": "week",
                "limit": str(limit),
            }
        )
        url = f"https://www.reddit.com/r/{subreddit}/search.json?{query}"
        try:
            listing = _fetch_listing(url)
        except Exception as exc:
            print(f"Skipping r/{subreddit}: {exc}", file=sys.stderr)
            continue
        for post in listing:
            data = post.get("data", {})
            permalink = data.get("permalink")
            if not permalink:
                continue
            items.append(
                SourceItem(
                    source="reddit",
                    topic_id=topic_id,
                    external_id=str(data.get("id", "")),
                    url=f"https://www.reddit.com{permalink}",
                    title=str(data.get("title", "")),
                    author=data.get("author"),
                    community=f"r/{subreddit}",
                    published_at=_reddit_timestamp(data.get("created_utc")),
                    score=data.get("score"),
                    comment_count=data.get("num_comments"),
                    raw_text=data.get("selftext") or None,
                    metadata={
                        "subreddit": subreddit,
                        "upvote_ratio": data.get("upvote_ratio"),
                        "link_flair_text": data.get("link_flair_text"),
                    },
                )
            )

    return _dedupe(items)


def _fetch_listing(url: str) -> list[dict[str, Any]]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    children = payload.get("data", {}).get("children", [])
    if not isinstance(children, list):
        return []
    return children


def _reddit_timestamp(value: Any) -> str | None:
    if value is None:
        return None
    from datetime import datetime, timezone

    return datetime.fromtimestamp(float(value), tz=timezone.utc).replace(microsecond=0).isoformat()


def _dedupe(items: list[SourceItem]) -> list[SourceItem]:
    seen: set[tuple[str, str]] = set()
    unique: list[SourceItem] = []
    for item in items:
        key = (item.source, item.external_id)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique
