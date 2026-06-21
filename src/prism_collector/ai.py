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


def _analyze_item(row: dict[str, Any], model: str) -> dict[str, Any]:
    content = _item_content(row, max_chars=7000)
    result = openai_json(
        model=model,
        system_prompt=(
            "You extract professional learning value from source material. "
            "Be concise, factual, and avoid inventing details not supported by the input."
        ),
        user_prompt=(
            "Analyze this source item for a self-learning knowledge base.\n\n"
            f"{content}\n\n"
            "Return highlights, concrete claims, tools mentioned, tags, difficulty, "
            "learning value, and follow-up questions."
        ),
        schema=ITEM_ANALYSIS_SCHEMA,
    )
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
