from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from prism_collector.models import SourceItem


def write_jsonl(path: Path, items: Iterable[SourceItem]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for item in items:
            handle.write(json.dumps(item.to_dict(), ensure_ascii=False, sort_keys=True))
            handle.write("\n")
            count += 1
    return count
