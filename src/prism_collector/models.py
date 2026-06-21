from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class SourceItem:
    source: str
    topic_id: str
    external_id: str
    url: str
    title: str
    author: str | None = None
    community: str | None = None
    published_at: str | None = None
    collected_at: str = field(default_factory=utc_now_iso)
    score: int | None = None
    comment_count: int | None = None
    raw_text: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
