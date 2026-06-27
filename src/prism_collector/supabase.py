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

    url, key = _supabase_credentials()

    endpoint = _table_endpoint(url, table)
    payload = json.dumps([_row(item) for item in items], ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=payload,
        method="POST",
        headers=_headers("resolution=merge-duplicates,return=minimal"),
    )

    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            if response.status not in (200, 201, 204):
                raise RuntimeError(f"unexpected Supabase status: {response.status}")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Supabase write failed: HTTP {exc.code}: {body}") from exc

    return len(items)


def fetch_existing_external_ids(source: str, external_ids: list[str]) -> set[str]:
    """Return the subset of external_ids that already exist for the given source.

    Used to skip re-scraping videos that are already stored.
    """
    if not external_ids:
        return set()
    in_list = ",".join(external_ids)
    rows = _get(
        "source_items",
        {
            "select": "external_id",
            "source": f"eq.{source}",
            "external_id": f"in.({in_list})",
        },
    )
    return {str(row["external_id"]) for row in rows if row.get("external_id")}


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
            "last_seen_at"
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
    rows = _get("source_items", filters)
    return _attach_item_analyses(rows)


def fetch_source_item_count() -> int | None:
    request = urllib.request.Request(
        _rest_url("source_items", {"select": "id", "limit": "1"}),
        headers={**_headers(), "Prefer": "count=exact"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            content_range = response.headers.get("Content-Range")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Supabase count failed: HTTP {exc.code}: {body}") from exc
    if not content_range or "/" not in content_range:
        return None
    total = content_range.rsplit("/", 1)[-1]
    if total == "*":
        return None
    return int(total)


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


def _active_key() -> str | None:
    return (
        os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        or os.getenv("SUPABASE_ANON_KEY")
        or os.getenv("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY")
        or os.getenv("SUPABASE_PUBLISHABLE_KEY")
    )


def active_key_kind() -> str:
    """Classify the key the reader will actually use.

    Returns one of 'secret', 'service_role', 'publishable', 'anon', 'jwt',
    'unknown', or 'missing'. Only 'secret' and 'service_role' bypass RLS — this
    is what determines whether the Data API can see rows that RLS would hide.
    """
    key = _active_key()
    if not key:
        return "missing"
    if key.startswith("sb_secret_"):
        return "secret"
    if key.startswith("sb_publishable_"):
        return "publishable"
    if key.startswith("eyJ"):
        return _jwt_role_kind(key)
    return "unknown"


def _jwt_role_kind(token: str) -> str:
    import base64

    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload.encode("utf-8")))
    except Exception:
        return "jwt"
    role = claims.get("role")
    return role if role in {"service_role", "anon"} else "jwt"


def key_bypasses_rls() -> bool:
    """True only when the active key elevates past Row Level Security."""
    return active_key_kind() in {"secret", "service_role"}


def using_service_role_key() -> bool:
    # Back-compat name: true only when the active key actually bypasses RLS, not
    # merely when the SUPABASE_SERVICE_ROLE_KEY env var happens to be set (it may
    # hold a publishable key, which does NOT bypass RLS).
    return key_bypasses_rls()


def _attach_item_analyses(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    ids = [str(row.get("id")) for row in rows if row.get("id") is not None]
    if not ids:
        return rows
    analyses = _get(
        "source_item_analyses",
        {
            "select": (
                "source_item_id,summary,highlights,claims,tools_mentioned,tags,"
                "difficulty,learning_value,follow_up_questions"
            ),
            "source_item_id": f"in.({','.join(ids)})",
        },
    )
    by_item_id: dict[str, list[dict[str, object]]] = {}
    for analysis in analyses:
        by_item_id.setdefault(str(analysis.get("source_item_id")), []).append(analysis)
    for row in rows:
        row["source_item_analyses"] = by_item_id.get(str(row.get("id")), [])
    return rows


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
    url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    key = (
        os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        or os.getenv("SUPABASE_ANON_KEY")
        or os.getenv("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY")
        or os.getenv("SUPABASE_PUBLISHABLE_KEY")
    )
    if not url or not key:
        raise SupabaseConfigError(
            "Supabase credentials are missing. Set SUPABASE_URL plus SUPABASE_SERVICE_ROLE_KEY/SUPABASE_ANON_KEY, or NEXT_PUBLIC_SUPABASE_URL plus NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY."
        )
    return url, key


def _headers(prefer: str | None = None) -> dict[str, str]:
    _, key = _supabase_credentials()
    headers = {
        "apikey": key,
        "Content-Type": "application/json",
    }
    if not key.startswith("sb_"):
        headers["Authorization"] = f"Bearer {key}"
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
