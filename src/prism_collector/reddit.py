from __future__ import annotations

import base64
import json
import os
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
    access_token = _oauth_access_token()

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
        url = _listing_url(subreddit, query, authenticated=bool(access_token))
        try:
            listing = _fetch_listing(url, access_token=access_token)
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


def _listing_url(subreddit: str, query: str, *, authenticated: bool) -> str:
    host = "oauth.reddit.com" if authenticated else "www.reddit.com"
    suffix = "" if authenticated else ".json"
    return f"https://{host}/r/{subreddit}/search{suffix}?{query}"


def _fetch_listing(url: str, access_token: str | None = None) -> list[dict[str, Any]]:
    headers = {"User-Agent": USER_AGENT}
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    children = payload.get("data", {}).get("children", [])
    if not isinstance(children, list):
        return []
    return children


def _oauth_access_token() -> str | None:
    client_id = os.getenv("REDDIT_CLIENT_ID")
    client_secret = os.getenv("REDDIT_CLIENT_SECRET")
    if not client_id or not client_secret:
        return None

    username = os.getenv("REDDIT_USERNAME")
    password = os.getenv("REDDIT_PASSWORD")
    if username and password:
        data = urllib.parse.urlencode(
            {
                "grant_type": "password",
                "username": username,
                "password": password,
            }
        ).encode("utf-8")
    else:
        data = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode("utf-8")

    credentials = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
    request = urllib.request.Request(
        "https://www.reddit.com/api/v1/access_token",
        data=data,
        method="POST",
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        print(f"Reddit OAuth unavailable, falling back to anonymous requests: {exc}", file=sys.stderr)
        return None

    token = payload.get("access_token")
    return str(token) if token else None


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
