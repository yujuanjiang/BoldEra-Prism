# BoldEra-Prism
Parsing, Retrieval, Intelligence, Synthesis, and Mapping. 
Turn chaotic information into structured intelligence.

## Data Collector MVP

This repository includes a first GitHub Actions-based collector for topic-focused
learning material from Reddit and YouTube. By default, collected items are
written to Supabase.

### What it does

- Reads topics from `config/topics.json`
- Focuses on YouTube collection by default
- Collects YouTube video metadata, transcripts, and high-comment discussion snapshots
- Upserts raw source items into a Supabase `source_items` table
- Uses AI to extract highlights, claims, tags, tools, and learning value
- Compares recent items for shared, unique, and controversial points
- Can still write JSONL files under `data/raw` for debugging

For YouTube rows, the collector stores every video it finds. When a public
transcript is available it is stored in `source_items.raw_text` (with
`metadata.transcript_available = true`); when the transcript is blocked or
missing, the video is still stored using its description as the `raw_text`
fallback and flagged with `metadata.transcript_available = false`, so a later
run can backfill the transcript once a proxy is configured. The video
description, view/like counts, transcript character count, and comment
snapshots are stored in `source_items.metadata`.

The collector fetches the newest videos for each topic, skips any video whose id
is already stored, and applies quality filters before scraping: videos must be
at least `YOUTUBE_MIN_AGE_DAYS` old (default 7, so they have had time to gather
comments) and have at least `YOUTUBE_MIN_COMMENTS` comments (default 50). Set
these as repository Variables to tune them; set either to `0` to disable.

To reach the target number of videos per topic (the `limit`, default 20), the
collector pages through search results until it has `limit` qualifying, not-yet
-stored videos, or it hits `YOUTUBE_MAX_SEARCH_PAGES` (default 6). Each search
page costs 100 YouTube quota units, so the cap bounds quota use when a topic
can't fill the target.
Comments are collected only when the video has more than 100 comments, and the
collector stores up to 100 top-level comment threads.

### Run locally

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONPATH=src python3 -m prism_collector.cli --topic ai-company-building --sources youtube --limit 5 --sink jsonl
PYTHONPATH=src python3 -m prism_collector.process_cli --topic ai-company-building --dry-run
```

### Run the reader UI

Install the UI extra and start Streamlit:

```bash
python3 -m pip install streamlit
SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... PYTHONPATH=src python3 -m streamlit run app/streamlit_app.py
```

The Streamlit app also loads `.env` and `.env.local` automatically. If you have
frontend-style Supabase values, these are accepted for read-only dashboard use:

```text
NEXT_PUBLIC_SUPABASE_URL
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY
```

You can also paste those values into the **Connect Supabase** panel in the
Streamlit sidebar for the current local session.

If the Supabase Data API shows zero rows while the SQL Editor shows data, paste
the project's Postgres connection string into the sidebar **Database URL** field
or set:

```text
SUPABASE_DB_URL
```

The app provides:

- `Today`: recent collected items with summaries and reading controls
- `Highlights`: extracted ideas from analyzed items
- `Debates`: similar, unique, and controversial points across sources
- `Saved`: items you marked for later

To validate the setup without network calls:

```bash
PYTHONPATH=src python3 -m prism_collector.cli --topic ai-company-building --dry-run
```

### Run on GitHub Actions

Open the **Collect Topic Data** workflow and trigger it manually with:

- `topic`: `ai-company-building`, `ai-investing`, `ai-agents-skills`, `ai-work-productivity`, or `ai-life-productivity`
- `sources`: `youtube` by default; `reddit` is currently paused
- `limit`: number of items per source query
- `dry_run`: validates configuration without calling source APIs
- `sink`: `supabase` or `jsonl`
- `run_ai`: analyzes Supabase source items after collection
- `compare_limit`: recent items to compare for similar/controversial points

The workflow also runs every Monday at 12:17 UTC.

### Secrets

Run these migrations in your Supabase project first:

```text
supabase/migrations/001_source_items.sql
supabase/migrations/002_ai_layer.sql
supabase/migrations/003_reader_ui_state.sql
```

Add these repository secrets for Supabase writes:

```text
SUPABASE_URL
SUPABASE_SERVICE_ROLE_KEY
```

Add this repository secret for AI processing:

```text
OPENAI_API_KEY
OPENAI_MODEL   # optional, defaults to gpt-4.1-mini
```

Add this repository secret for YouTube collection:

```text
YOUTUBE_API_KEY
```

GitHub Actions runs from cloud IPs, which YouTube blocks for transcript
requests (this is the `RequestBlocked` / `IpBlocked` error). Transcript
collection in Actions **requires** a rotating residential proxy. Configure one
of these proxy options:

```text
YOUTUBE_TRANSCRIPT_WEBSHARE_USERNAME
YOUTUBE_TRANSCRIPT_WEBSHARE_PASSWORD
YOUTUBE_TRANSCRIPT_WEBSHARE_LOCATIONS   # optional, e.g. us,ca
```

> Important: on Webshare, purchase the **"Residential"** package (rotating
> residential proxies). Do **not** buy "Proxy Server" or "Static Residential" —
> those are datacenter/static IPs that YouTube also blocks. Use the "Proxy
> Username" and "Proxy Password" from your Webshare proxy settings (not your
> account login). The workflow logs whether a proxy is configured and will warn
> if it is missing.

or:

```text
YOUTUBE_TRANSCRIPT_PROXY_HTTP_URL
YOUTUBE_TRANSCRIPT_PROXY_HTTPS_URL
```

The transcript library recommends rotating residential proxies for cloud
deployments; another low-complexity option is to run the workflow on a local
self-hosted runner instead of GitHub-hosted Actions.

Reddit collection is currently paused. If you later get approved Reddit API
access, these secrets can be used to re-enable it:

```text
REDDIT_CLIENT_ID
REDDIT_CLIENT_SECRET
REDDIT_USERNAME    # optional, recommended for a script app
REDDIT_PASSWORD    # optional, recommended for a script app
```

Without the YouTube secret, the collector skips YouTube. For scheduled runs,
Supabase secrets are required because the default sink is `supabase`.

### Next steps

- Add transcript extraction for YouTube videos
- Add pgvector embeddings for semantic search
- Add ranking, deduplication across runs, and topic learning-path generation
