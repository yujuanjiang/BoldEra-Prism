from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import replace

from prism_collector.models import SourceItem


class SupabaseConfigError(RuntimeError):
    pass


def write_supabase(items: list[SourceItem], table: str = "source_items") -> int:
    if not items:
        return 0

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
    if not url or not key:
        raise SupabaseConfigError(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY must be set"
        )

    endpoint = _table_endpoint(url, table)
    payload = json.dumps([_row(item) for item in items], ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=payload,
        method="POST",
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates,return=minimal",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            if response.status not in (200, 201, 204):
                raise RuntimeError(f"unexpected Supabase status: {response.status}")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Supabase write failed: HTTP {exc.code}: {body}") from exc

    return len(items)


def fetch_source_items_without_analysis(topic_id: str, limit: int = 10) -> list[dict[str, object]]:
    existing = _get(
        "source_item_analyses",
        {
            "select": "source_item_id",
            "topic_id": f"eq.{topic_id}",
        },
    )
    analyzed_ids = {str(row["source_item_id"]) for row in existing if row.get("source_item_id")}
    rows = fetch_recent_source_items(topic_id=topic_id, limit=max(limit * 3, limit))
    unprocessed = [row for row in rows if str(row.get("id")) not in analyzed_ids]
    return unprocessed[:limit]


def fetch_recent_source_items(topic_id: str, limit: int = 10) -> list[dict[str, object]]:
    return _get(
        "source_items",
        {
            "select": (
                "id,source,topic_id,external_id,url,title,author,community,published_at,"
                "collected_at,score,comment_count,raw_text,metadata,user_status,saved,user_note,"
                "last_seen_at"
            ),
            "topic_id": f"eq.{topic_id}",
            "order": "collected_at.desc",
            "limit": str(limit),
        },
    )


def fetch_reader_items(
    *,
    topic_id: str | None = None,
    status: str | None = None,
    saved: bool | None = None,
    limit: int = 50,
) -> list[dict[str, object]]:
    filters = {
        "select": (
            "id,source,topic_id,external_id,url,title,author,community,published_at,"
            "collected_at,score,comment_count,raw_text,metadata,user_status,saved,user_note,"
            "last_seen_at,source_item_analyses(summary,highlights,claims,tools_mentioned,tags,"
            "difficulty,learning_value,follow_up_questions)"
        ),
        "order": "collected_at.desc",
        "limit": str(limit),
    }
    if topic_id:
        filters["topic_id"] = f"eq.{topic_id}"
    if status and status != "all":
        filters["user_status"] = f"eq.{status}"
    if saved is not None:
        filters["saved"] = f"eq.{str(saved).lower()}"
    return _get("source_items", filters)


def fetch_topic_comparisons(topic_id: str | None = None, limit: int = 10) -> list[dict[str, object]]:
    filters = {
        "select": (
            "id,topic_id,model,source_item_ids,shared_points,controversial_points,"
            "unique_points,learning_path,open_questions,created_at"
        ),
        "order": "created_at.desc",
        "limit": str(limit),
    }
    if topic_id:
        filters["topic_id"] = f"eq.{topic_id}"
    return _get("topic_comparisons", filters)


def update_source_item_state(
    item_id: int,
    *,
    user_status: str | None = None,
    saved: bool | None = None,
    user_note: str | None = None,
    mark_seen: bool = False,
) -> None:
    row: dict[str, object] = {}
    if user_status is not None:
        row["user_status"] = user_status
    if saved is not None:
        row["saved"] = saved
    if user_note is not None:
        row["user_note"] = user_note
    if mark_seen:
        from prism_collector.models import utc_now_iso

        row["last_seen_at"] = utc_now_iso()
    if not row:
        return
    _patch("source_items", {"id": f"eq.{item_id}"}, row)


def upsert_item_analyses(rows: list[dict[str, object]]) -> int:
    if not rows:
        return 0
    _post_rows(
        "source_item_analyses",
        rows,
        on_conflict="source_item_id",
        prefer="resolution=merge-duplicates,return=minimal",
    )
    return len(rows)


def insert_topic_comparison(row: dict[str, object]) -> int:
    _post_rows("topic_comparisons", [row], prefer="return=minimal")
    return 1


def _table_endpoint(supabase_url: str, table: str) -> str:
    base = supabase_url.rstrip("/")
    encoded_table = urllib.parse.quote(table, safe="")
    return f"{base}/rest/v1/{encoded_table}?on_conflict=source,external_id"


def _rest_url(table: str, params: dict[str, str] | None = None) -> str:
    url, _ = _supabase_credentials()
    base = url.rstrip("/")
    encoded_table = urllib.parse.quote(table, safe="")
    query = urllib.parse.urlencode(params or {})
    suffix = f"?{query}" if query else ""
    return f"{base}/rest/v1/{encoded_table}{suffix}"


def _supabase_credentials() -> tuple[str, str]:
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
    if not url or not key:
        raise SupabaseConfigError(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set to write to Supabase"
        )
    return url, key


def _headers(prefer: str | None = None) -> dict[str, str]:
    _, key = _supabase_credentials()
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    return headers


def _get(table: str, params: dict[str, str]) -> list[dict[str, object]]:
    request = urllib.request.Request(_rest_url(table, params), headers=_headers(), method="GET")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Supabase read failed: HTTP {exc.code}: {body}") from exc


def _post_rows(
    table: str,
    rows: list[dict[str, object]],
    *,
    on_conflict: str | None = None,
    prefer: str,
) -> None:
    params = {"on_conflict": on_conflict} if on_conflict else None
    request = urllib.request.Request(
        _rest_url(table, params),
        data=json.dumps(rows, ensure_ascii=False, default=str).encode("utf-8"),
        method="POST",
        headers=_headers(prefer),
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            if response.status not in (200, 201, 204):
                raise RuntimeError(f"unexpected Supabase status: {response.status}")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Supabase write failed: HTTP {exc.code}: {body}") from exc


def _patch(table: str, filters: dict[str, str], row: dict[str, object]) -> None:
    request = urllib.request.Request(
        _rest_url(table, filters),
        data=json.dumps(row, ensure_ascii=False, default=str).encode("utf-8"),
        method="PATCH",
        headers=_headers("return=minimal"),
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            if response.status not in (200, 201, 204):
                raise RuntimeError(f"unexpected Supabase status: {response.status}")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Supabase update failed: HTTP {exc.code}: {body}") from exc


def _row(item: SourceItem) -> dict[str, object]:
    # Keep unknown metadata JSON-compatible before sending it to PostgREST.
    clean_item = replace(item, metadata=json.loads(json.dumps(item.metadata, default=str)))
    return clean_item.to_dict()
