# BoldEra-Prism
Parsing, Retrieval, Intelligence, Synthesis, and Mapping. 
Turn chaotic information into structured intelligence.

## Data Collector MVP

This repository includes a first GitHub Actions-based collector for topic-focused
learning material from Reddit and YouTube. By default, collected items are
written to Supabase.

### What it does

- Reads topics from `config/topics.json`
- Collects recent Reddit posts for configured subreddits and keywords
- Collects YouTube search results when `YOUTUBE_API_KEY` is configured
- Upserts raw source items into a Supabase `source_items` table
- Uses AI to extract highlights, claims, tags, tools, and learning value
- Compares recent items for shared, unique, and controversial points
- Can still write JSONL files under `data/raw` for debugging

### Run locally

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONPATH=src python3 -m prism_collector.cli --topic ai-programming --sources reddit --limit 5 --sink jsonl
PYTHONPATH=src python3 -m prism_collector.process_cli --topic ai-programming --dry-run
```

### Run the reader UI

Install the UI extra and start Streamlit:

```bash
python3 -m pip install streamlit
SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... PYTHONPATH=src python3 -m streamlit run app/streamlit_app.py
```

The app provides:

- `Today`: recent collected items with summaries and reading controls
- `Highlights`: extracted ideas from analyzed items
- `Debates`: similar, unique, and controversial points across sources
- `Saved`: items you marked for later

To validate the setup without network calls:

```bash
PYTHONPATH=src python3 -m prism_collector.cli --topic ai-programming --dry-run
```

### Run on GitHub Actions

Open the **Collect Topic Data** workflow and trigger it manually with:

- `topic`: `ai-programming` or `investing`
- `sources`: `reddit`, `youtube`, or `reddit,youtube`
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

Add this repository secret if you want YouTube collection:

```text
YOUTUBE_API_KEY
```

Without the YouTube secret, the collector skips YouTube and still works for
Reddit. For scheduled runs, Supabase secrets are required because the default
sink is `supabase`.

### Next steps

- Add transcript extraction for YouTube videos
- Add pgvector embeddings for semantic search
- Add ranking, deduplication across runs, and topic learning-path generation
