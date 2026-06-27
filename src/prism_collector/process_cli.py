from __future__ import annotations

import argparse
from pathlib import Path

from prism_collector.ai import analyze_topic
from prism_collector.config import load_topics, select_topics


def main() -> int:
    parser = argparse.ArgumentParser(description="Run AI processing for collected source items.")
    parser.add_argument(
        "--topic",
        required=True,
        help="Topic id to process, or 'all' to process every topic",
    )
    parser.add_argument("--config", default="config/topics.json", help="Path to topic config")
    parser.add_argument("--limit", type=int, default=10, help="Unprocessed source items to analyze")
    parser.add_argument(
        "--compare-limit",
        type=int,
        default=8,
        help="Recent source items to compare for similarities and controversies",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate processing arguments without calling Supabase or OpenAI",
    )
    args = parser.parse_args()

    topic_ids = [topic["id"] for topic in select_topics(load_topics(Path(args.config)), args.topic)]

    if args.dry_run:
        for topic_id in topic_ids:
            print(
                f"Validated AI processing for topic '{topic_id}' "
                f"with limit={args.limit}, compare_limit={args.compare_limit}"
            )
        return 0

    total_analyzed = 0
    total_comparisons = 0
    for topic_id in topic_ids:
        result = analyze_topic(topic_id, limit=args.limit, compare_limit=args.compare_limit)
        print(
            f"[{topic_id}] analyzed {result['analyzed']} items and wrote "
            f"{result['comparisons']} comparison rows"
        )
        total_analyzed += result["analyzed"]
        total_comparisons += result["comparisons"]

    print(
        f"Total: analyzed {total_analyzed} items and wrote {total_comparisons} "
        f"comparison rows across {len(topic_ids)} topic(s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
