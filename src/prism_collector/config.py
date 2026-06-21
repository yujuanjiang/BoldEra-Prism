from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_topics(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    topics = payload.get("topics", [])
    if not isinstance(topics, list):
        raise ValueError("config must contain a 'topics' list")
    return topics


def find_topic(topics: list[dict[str, Any]], topic_id: str) -> dict[str, Any]:
    for topic in topics:
        if topic.get("id") == topic_id:
            return topic
    available = ", ".join(str(topic.get("id")) for topic in topics)
    raise ValueError(f"unknown topic '{topic_id}'. Available topics: {available}")
