from __future__ import annotations

import argparse
from pathlib import Path

from prism_collector.config import load_topics, select_topics
from prism_collector.io import write_jsonl
from prism_collector.reddit import collect_reddit
from prism_collector.supabase import fetch_existing_external_ids, write_supabase
from prism_collector.youtube import collect_youtube


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect topic-based source material.")
    parser.add_argument(
        "--topic",
        required=True,
        help="Topic id from config/topics.json, or 'all' to collect every topic",
    )
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
        default="youtube",
        help="Comma-separated sources to run. Default: youtube",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate configuration without calling external APIs",
    )
    args = parser.parse_args()

    topics = load_topics(Path(args.config))
    selected = select_topics(topics, args.topic)
    sources = {source.strip().lower() for source in args.sources.split(",") if source.strip()}

    if args.dry_run:
        for topic in selected:
            print(f"Validated topic '{topic['id']}' with sources: {', '.join(sorted(sources))}")
        return 0

    # When writing to Supabase, skip videos already stored (dedup by url/external_id)
    # so existing videos are not re-scraped. JSONL runs collect everything.
    skip_existing = None
    if args.sink == "supabase":
        skip_existing = lambda ids: fetch_existing_external_ids("youtube", ids)  # noqa: E731

    total = 0
    # Collect and write per topic so a failure on one topic does not discard the
    # items already gathered for the others.
    for topic in selected:
        items = []
        if "reddit" in sources:
            items.extend(collect_reddit(topic, limit=args.limit))
        if "youtube" in sources:
            items.extend(collect_youtube(topic, limit=args.limit, skip_existing=skip_existing))

        if args.sink == "jsonl":
            output_path = Path(args.output) / f"{topic['id']}.jsonl"
            count = write_jsonl(output_path, items)
            print(f"Wrote {count} items to {output_path}")
        else:
            count = write_supabase(items, table=args.supabase_table)
            print(
                f"Wrote {count} items to Supabase table '{args.supabase_table}' "
                f"for topic '{topic['id']}'"
            )
        total += count

    print(f"Total: wrote {total} items across {len(selected)} topic(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
