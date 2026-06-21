from __future__ import annotations

import argparse
from pathlib import Path

from prism_collector.config import find_topic, load_topics
from prism_collector.io import write_jsonl
from prism_collector.reddit import collect_reddit
from prism_collector.supabase import write_supabase
from prism_collector.youtube import collect_youtube


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect topic-based source material.")
    parser.add_argument("--topic", required=True, help="Topic id from config/topics.json")
    parser.add_argument("--config", default="config/topics.json", help="Path to topic config")
    parser.add_argument("--output", default="data/raw", help="Directory for JSONL output")
    parser.add_argument(
        "--sink",
        choices=("jsonl", "supabase"),
        default="supabase",
        help="Where collected items should be written",
    )
    parser.add_argument(
        "--supabase-table",
        default="source_items",
        help="Supabase table name for collected source items",
    )
    parser.add_argument("--limit", type=int, default=10, help="Items per source query")
    parser.add_argument(
        "--sources",
        default="reddit,youtube",
        help="Comma-separated sources to run: reddit,youtube",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate configuration without calling external APIs",
    )
    args = parser.parse_args()

    topics = load_topics(Path(args.config))
    topic = find_topic(topics, args.topic)
    sources = {source.strip().lower() for source in args.sources.split(",") if source.strip()}

    if args.dry_run:
        print(f"Validated topic '{topic['id']}' with sources: {', '.join(sorted(sources))}")
        return 0

    items = []
    if "reddit" in sources:
        items.extend(collect_reddit(topic, limit=args.limit))
    if "youtube" in sources:
        items.extend(collect_youtube(topic, limit=args.limit))

    if args.sink == "jsonl":
        output_path = Path(args.output) / f"{args.topic}.jsonl"
        count = write_jsonl(output_path, items)
        print(f"Wrote {count} items to {output_path}")
        return 0

    count = write_supabase(items, table=args.supabase_table)
    print(f"Wrote {count} items to Supabase table '{args.supabase_table}'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
