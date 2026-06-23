from __future__ import annotations

import json
import os
from typing import Any

from prism_collector.openai_client import openai_json
from prism_collector.supabase import (
    fetch_recent_source_items,
    fetch_source_items_without_analysis,
    insert_topic_comparison,
    upsert_item_analyses,
)


ITEM_ANALYSIS_SCHEMA = {
    "name": "source_item_analysis",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "summary",
            "highlights",
            "claims",
            "tools_mentioned",
            "tags",
            "difficulty",
            "learning_value",
            "follow_up_questions",
        ],
        "properties": {
            "summary": {"type": "string"},
            "highlights": {"type": "array", "items": {"type": "string"}},
            "claims": {"type": "array", "items": {"type": "string"}},
            "tools_mentioned": {"type": "array", "items": {"type": "string"}},
            "tags": {"type": "array", "items": {"type": "string"}},
            "difficulty": {
                "type": "string",
                "enum": ["beginner", "intermediate", "advanced", "mixed", "unknown"],
            },
            "learning_value": {"type": "integer", "minimum": 1, "maximum": 10},
            "follow_up_questions": {"type": "array", "items": {"type": "string"}},
        },
    },
}


TOPIC_COMPARISON_SCHEMA = {
    "name": "topic_comparison",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "shared_points",
            "controversial_points",
            "unique_points",
            "learning_path",
            "open_questions",
        ],
        "properties": {
            "shared_points": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["point", "source_item_ids"],
                    "properties": {
                        "point": {"type": "string"},
                        "source_item_ids": {"type": "array", "items": {"type": "integer"}},
                    },
                },
            },
            "controversial_points": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["issue", "positions", "source_item_ids"],
                    "properties": {
                        "issue": {"type": "string"},
                        "positions": {"type": "array", "items": {"type": "string"}},
                        "source_item_ids": {"type": "array", "items": {"type": "integer"}},
                    },
                },
            },
            "unique_points": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["point", "source_item_id"],
                    "properties": {
                        "point": {"type": "string"},
                        "source_item_id": {"type": "integer"},
                    },
                },
            },
            "learning_path": {"type": "array", "items": {"type": "string"}},
            "open_questions": {"type": "array", "items": {"type": "string"}},
        },
    },
}


def analyze_topic(topic_id: str, limit: int = 10, compare_limit: int = 8) -> dict[str, int]:
    model = os.getenv("OPENAI_MODEL") or "gpt-4.1-mini"
    rows = fetch_source_items_without_analysis(topic_id=topic_id, limit=limit)
    analyses = [_analyze_item(row, model=model) for row in rows]
    analyzed_count = upsert_item_analyses(analyses) if analyses else 0

    comparison_count = 0
    comparison_rows = fetch_recent_source_items(topic_id=topic_id, limit=compare_limit)
    if len(comparison_rows) >= 2:
        comparison = _compare_items(topic_id=topic_id, rows=comparison_rows, model=model)
        insert_topic_comparison(comparison)
        comparison_count = 1

    return {"analyzed": analyzed_count, "comparisons": comparison_count}


def _positive_int_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, ""))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


# Characters of source text analyzed per AI call. The whole transcript is always
# covered: text longer than one chunk is split and analyzed in a map-reduce pass.
# gpt-4.1-mini has a large context window, so this stays well within limits while
# keeping each call reliable. Override with OPENAI_ITEM_CHUNK_CHARS if needed.
ITEM_TEXT_CHUNK_CHARS = _positive_int_env("OPENAI_ITEM_CHUNK_CHARS", 40000)

ITEM_ANALYSIS_SYSTEM_PROMPT = (
    "You extract professional learning value from source material. "
    "Be concise, factual, and avoid inventing details not supported by the input."
)


def _analyze_item(row: dict[str, Any], model: str) -> dict[str, Any]:
    header = _item_header(row)
    raw_text = str(row.get("raw_text") or "").strip()
    chunks = _chunk_text(raw_text, ITEM_TEXT_CHUNK_CHARS)

    if len(chunks) <= 1:
        result = _analyze_text_segment(header, chunks[0] if chunks else "", model)
    else:
        # Map: analyze every chunk so the entire transcript is covered.
        partials = [
            _analyze_text_segment(header, chunk, model, part=(index + 1, len(chunks)))
            for index, chunk in enumerate(chunks)
        ]
        # Reduce: consolidate the per-chunk analyses into one coherent analysis.
        result = _merge_item_analyses(header, partials, model)

    return {
        "source_item_id": row["id"],
        "topic_id": row["topic_id"],
        "model": model,
        "summary": result["summary"],
        "highlights": result["highlights"],
        "claims": result["claims"],
        "tools_mentioned": result["tools_mentioned"],
        "tags": result["tags"],
        "difficulty": result["difficulty"],
        "learning_value": result["learning_value"],
        "follow_up_questions": result["follow_up_questions"],
        "raw_response": result,
    }


def _analyze_text_segment(
    header: str,
    body: str,
    model: str,
    part: tuple[int, int] | None = None,
) -> dict[str, Any]:
    if part is not None:
        index, total = part
        scope = (
            f"This is part {index} of {total} of a longer transcript that was split for "
            "analysis. Analyze ONLY the text in this part, capturing every notable point it "
            "contains so nothing is lost when the parts are combined later.\n\n"
        )
    else:
        scope = "Analyze the full source item below.\n\n"

    return openai_json(
        model=model,
        system_prompt=ITEM_ANALYSIS_SYSTEM_PROMPT,
        user_prompt=(
            "Analyze this source item for a self-learning knowledge base.\n\n"
            f"{scope}"
            f"Source metadata:\n{header}\n\n"
            f"Source text:\n{body}\n\n"
            "Return a summary plus highlights, concrete claims, tools mentioned, tags, "
            "difficulty, learning value, and follow-up questions."
        ),
        schema=ITEM_ANALYSIS_SCHEMA,
    )


def _merge_item_analyses(
    header: str, partials: list[dict[str, Any]], model: str
) -> dict[str, Any]:
    return openai_json(
        model=model,
        system_prompt=ITEM_ANALYSIS_SYSTEM_PROMPT,
        user_prompt=(
            "The source item below was too long to analyze at once, so it was split into "
            "parts that were each analyzed separately. Consolidate the per-part analyses "
            "into ONE analysis covering the entire item. Write a single coherent summary "
            "that spans the whole item, merge and de-duplicate the highlights, claims, "
            "tools, tags, and follow-up questions, choose the overall difficulty, and set "
            "learning value for the item as a whole.\n\n"
            f"Source metadata:\n{header}\n\n"
            f"Per-part analyses (JSON):\n{json.dumps(partials, ensure_ascii=False)}"
        ),
        schema=ITEM_ANALYSIS_SCHEMA,
    )


def _compare_items(topic_id: str, rows: list[dict[str, Any]], model: str) -> dict[str, Any]:
    digest = "\n\n".join(_item_content(row, max_chars=2500) for row in rows)
    result = openai_json(
        model=model,
        system_prompt=(
            "You compare learning materials across sources. Identify only similarities, "
            "tensions, contradictions, and gaps that are grounded in the provided items."
        ),
        user_prompt=(
            f"Compare these source items for topic '{topic_id}'.\n\n"
            f"{digest}\n\n"
            "Find shared points, controversial points, unique points, a practical learning "
            "path, and open questions."
        ),
        schema=TOPIC_COMPARISON_SCHEMA,
    )
    return {
        "topic_id": topic_id,
        "model": model,
        "source_item_ids": [row["id"] for row in rows],
        "shared_points": result["shared_points"],
        "controversial_points": result["controversial_points"],
        "unique_points": result["unique_points"],
        "learning_path": result["learning_path"],
        "open_questions": result["open_questions"],
        "raw_response": result,
    }


def _item_header(row: dict[str, Any]) -> str:
    """JSON metadata for an item, excluding the (potentially huge) raw_text."""
    return json.dumps(
        {
            "id": row.get("id"),
            "source": row.get("source"),
            "topic_id": row.get("topic_id"),
            "title": row.get("title"),
            "url": row.get("url"),
            "author": row.get("author"),
            "community": row.get("community"),
            "published_at": row.get("published_at"),
            "score": row.get("score"),
            "comment_count": row.get("comment_count"),
            "metadata": row.get("metadata"),
        },
        ensure_ascii=False,
    )


def _chunk_text(text: str, size: int) -> list[str]:
    """Split text into <=size-char chunks, breaking on whitespace where possible.

    Returns an empty list for empty text and a single-element list when the text
    already fits, so the entire transcript is always covered with no truncation.
    """
    text = text.strip()
    if not text:
        return []
    if size <= 0 or len(text) <= size:
        return [text]

    chunks: list[str] = []
    start = 0
    length = len(text)
    while start < length:
        end = min(start + size, length)
        if end < length:
            boundary = text.rfind(" ", start, end)
            if boundary > start:
                end = boundary
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = max(end, start + 1)
    return chunks


def _item_content(row: dict[str, Any], max_chars: int) -> str:
    text = {
        "id": row.get("id"),
        "source": row.get("source"),
        "topic_id": row.get("topic_id"),
        "title": row.get("title"),
        "url": row.get("url"),
        "author": row.get("author"),
        "community": row.get("community"),
        "published_at": row.get("published_at"),
        "score": row.get("score"),
        "comment_count": row.get("comment_count"),
        "raw_text": row.get("raw_text"),
        "metadata": row.get("metadata"),
    }
    content = json.dumps(text, ensure_ascii=False)
    if len(content) <= max_chars:
        return content
    return content[: max_chars - 20] + "...[truncated]"
