from __future__ import annotations

import os
from typing import Any


def db_configured() -> bool:
    return bool(os.getenv("SUPABASE_DB_URL"))


def fetch_reader_items_db(
    *,
    topic_id: str | None = None,
    status: str | None = None,
    saved: bool | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    query = """
        select
          si.id,
          si.source,
          si.topic_id,
          si.external_id,
          si.url,
          si.title,
          si.author,
          si.community,
          si.published_at,
          si.collected_at,
          si.score,
          si.comment_count,
          si.raw_text,
          si.metadata,
          si.user_status,
          si.saved,
          si.user_note,
          si.last_seen_at,
          coalesce(
            jsonb_agg(
              jsonb_build_object(
                'summary', sia.summary,
                'highlights', sia.highlights,
                'claims', sia.claims,
                'tools_mentioned', sia.tools_mentioned,
                'tags', sia.tags,
                'difficulty', sia.difficulty,
                'learning_value', sia.learning_value,
                'follow_up_questions', sia.follow_up_questions
              )
            ) filter (where sia.id is not null),
            '[]'::jsonb
          ) as source_item_analyses
        from public.source_items si
        left join public.source_item_analyses sia on sia.source_item_id = si.id
        where (%s is null or si.topic_id = %s)
          and (%s is null or %s = 'all' or si.user_status = %s)
          and (%s is null or si.saved = %s)
        group by si.id
        order by si.collected_at desc
        limit %s
    """
    params = (topic_id, topic_id, status, status, status, saved, saved, limit)
    return _fetch_rows(query, params)


def fetch_source_item_count_db() -> int:
    rows = _fetch_rows("select count(*) as count from public.source_items", ())
    return int(rows[0]["count"]) if rows else 0


def fetch_topic_comparisons_db(topic_id: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
    query = """
        select
          id,
          topic_id,
          model,
          source_item_ids,
          shared_points,
          controversial_points,
          unique_points,
          learning_path,
          open_questions,
          created_at
        from public.topic_comparisons
        where (%s is null or topic_id = %s)
        order by created_at desc
        limit %s
    """
    return _fetch_rows(query, (topic_id, topic_id, limit))


def update_source_item_state_db(
    item_id: int,
    *,
    user_status: str | None = None,
    saved: bool | None = None,
    user_note: str | None = None,
    mark_seen: bool = False,
) -> None:
    assignments: list[str] = []
    params: list[Any] = []
    if user_status is not None:
        assignments.append("user_status = %s")
        params.append(user_status)
    if saved is not None:
        assignments.append("saved = %s")
        params.append(saved)
    if user_note is not None:
        assignments.append("user_note = %s")
        params.append(user_note)
    if mark_seen:
        assignments.append("last_seen_at = now()")
    if not assignments:
        return
    params.append(item_id)
    _execute(f"update public.source_items set {', '.join(assignments)} where id = %s", params)


def _fetch_rows(query: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    import psycopg
    from psycopg.rows import dict_row

    db_url = os.getenv("SUPABASE_DB_URL")
    if not db_url:
        raise RuntimeError("SUPABASE_DB_URL is not set")
    with psycopg.connect(db_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            return [dict(row) for row in cur.fetchall()]


def _execute(query: str, params: list[Any]) -> None:
    import psycopg

    db_url = os.getenv("SUPABASE_DB_URL")
    if not db_url:
        raise RuntimeError("SUPABASE_DB_URL is not set")
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
        conn.commit()
