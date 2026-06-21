from __future__ import annotations

import argparse

from prism_collector.ai import analyze_topic


def main() -> int:
    parser = argparse.ArgumentParser(description="Run AI processing for collected source items.")
    parser.add_argument("--topic", required=True, help="Topic id to process")
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

    if args.dry_run:
        print(
            f"Validated AI processing for topic '{args.topic}' "
            f"with limit={args.limit}, compare_limit={args.compare_limit}"
        )
        return 0

    result = analyze_topic(args.topic, limit=args.limit, compare_limit=args.compare_limit)
    print(f"Analyzed {result['analyzed']} items and wrote {result['comparisons']} comparison rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
