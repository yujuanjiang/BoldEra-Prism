from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from prism_collector.config import load_topics
from prism_collector.env import load_local_env
from prism_collector.supabase import (
    SupabaseConfigError,
    active_key_kind,
    fetch_reader_items,
    fetch_source_item_count,
    fetch_topic_comparisons,
    key_bypasses_rls,
    update_source_item_state,
    using_service_role_key,
)
from prism_collector.supabase_db import (
    db_configured,
    fetch_reader_items_db,
    fetch_source_item_count_db,
    fetch_topic_comparisons_db,
    update_source_item_state_db,
)

load_local_env(ROOT)

# When deployed (e.g. Streamlit Community Cloud), configuration is supplied via
# st.secrets rather than .env.local. Mirror those values into os.environ so the
# existing os.getenv-based config (Supabase URL/keys, SUPABASE_DB_URL) keeps
# working unchanged. Local runs without a secrets file are unaffected.
try:
    for _secret_key, _secret_value in st.secrets.items():
        if isinstance(_secret_value, str):
            os.environ.setdefault(_secret_key, _secret_value)
except Exception:
    pass

STATUSES = ["unread", "reading", "read", "archived"]


st.set_page_config(
    page_title="Prism Desk",
    page_icon="PR",
    layout="wide",
    initial_sidebar_state="expanded",
)


st.markdown(
    """
    <style>
      .block-container { padding-top: 1.6rem; }
      [data-testid="stSidebar"] { background: #f7f7f4; }
      h1, h2, h3 { letter-spacing: 0; }
      .prism-card {
        border: 1px solid #e1dfd8;
        border-radius: 8px;
        padding: 16px 18px;
        margin: 0 0 14px 0;
        background: #fffdf8;
      }
      .muted {
        color: #6d6a63;
        font-size: 0.9rem;
      }
      .chip {
        display: inline-block;
        border: 1px solid #dedbd2;
        border-radius: 999px;
        padding: 2px 9px;
        margin: 2px 4px 2px 0;
        background: #f8f6ef;
        color: #34322d;
        font-size: 0.78rem;
      }
      .score {
        font-weight: 700;
        color: #325c46;
      }
    </style>
    """,
    unsafe_allow_html=True,
)


def main() -> None:
    topics = load_topics(ROOT / "config" / "topics.json")
    topic_options = ["all"] + [str(topic["id"]) for topic in topics]

    with st.sidebar:
        st.title("Prism Desk")
        st.caption("Daily learning dashboard")
        view = st.radio(
            "View",
            ["Today", "Highlights", "Debates", "Saved"],
            label_visibility="collapsed",
        )
        topic_id = st.selectbox("Topic", topic_options, index=0)
        status = st.selectbox("Status", ["all", *STATUSES], index=0)
        limit = st.slider("Items", min_value=10, max_value=100, value=30, step=10)
        st.divider()
        render_connection_form()
        render_connection_diagnostics()
        st.divider()
        st.caption("Environment")
        _env_status("SUPABASE_URL")
        _env_status("SUPABASE_SERVICE_ROLE_KEY", secret=True)
        _env_status("SUPABASE_ANON_KEY", secret=True)
        _env_status("NEXT_PUBLIC_SUPABASE_URL")
        _env_status("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY", secret=True)
        _env_status("SUPABASE_DB_URL", secret=True)

    selected_topic = None if topic_id == "all" else topic_id

    try:
        if view == "Debates":
            render_debates(selected_topic)
            return

        saved_filter = True if view == "Saved" else None
        rows = fetch_reader_rows(
            topic_id=selected_topic,
            status=status,
            saved=saved_filter,
            limit=limit,
        )
    except SupabaseConfigError as exc:
        st.error(str(exc))
        st.info(
            "Use the connection form in the sidebar, or add NEXT_PUBLIC_SUPABASE_URL "
            "and NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY to .env.local."
        )
        return
    except Exception as exc:
        st.error(f"Could not load data: {exc}")
        return

    if view == "Today":
        render_today(rows)
    elif view == "Highlights":
        render_highlights(rows)
    else:
        render_saved(rows)


def render_today(rows: list[dict[str, Any]]) -> None:
    st.title("Today")
    st.caption("Fresh source material, AI summaries, and reading decisions.")
    render_metrics(rows)
    st.divider()

    if not rows:
        render_empty_items_help()
        return

    for row in rows:
        render_source_card(row)


def render_highlights(rows: list[dict[str, Any]]) -> None:
    st.title("Highlights")
    st.caption("Ideas extracted from recent source items.")

    highlights = []
    for row in rows:
        analysis = first_analysis(row)
        for highlight in analysis.get("highlights", []) if analysis else []:
            highlights.append((row, highlight))

    if not highlights:
        st.info("No highlights yet. Run the AI processing workflow after collection.")
        return

    for row, highlight in highlights:
        st.markdown(
            f"""
            <div class="prism-card">
              <div class="muted">{source_label(row)} · {row.get("topic_id", "")}</div>
              <h4>{escape(row.get("title", "Untitled"))}</h4>
              <p>{escape(highlight)}</p>
              <a href="{row.get("url", "#")}" target="_blank">Open source</a>
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_debates(topic_id: str | None) -> None:
    st.title("Debates")
    st.caption("Similarities, tensions, and open questions across recent material.")

    try:
        comparisons = fetch_comparison_rows(topic_id=topic_id, limit=10)
    except SupabaseConfigError as exc:
        st.error(str(exc))
        return
    except Exception as exc:
        st.error(f"Could not load comparisons: {exc}")
        return

    if not comparisons:
        st.info("No comparison snapshots yet. Run the AI processing workflow with at least two source items.")
        return

    for comparison in comparisons:
        st.subheader(f"{comparison.get('topic_id', 'Topic')} · {comparison.get('created_at', '')}")
        cols = st.columns(2)
        with cols[0]:
            st.markdown("**Shared Points**")
            render_bullets(comparison.get("shared_points", []), "point")
            st.markdown("**Unique Points**")
            render_bullets(comparison.get("unique_points", []), "point")
        with cols[1]:
            st.markdown("**Controversial Points**")
            for item in comparison.get("controversial_points", []) or []:
                issue = item.get("issue", "") if isinstance(item, dict) else str(item)
                positions = item.get("positions", []) if isinstance(item, dict) else []
                st.warning(issue)
                render_plain_bullets(positions)
            st.markdown("**Open Questions**")
            render_plain_bullets(comparison.get("open_questions", []))
        with st.expander("Learning path"):
            render_plain_bullets(comparison.get("learning_path", []))
        st.divider()


def render_saved(rows: list[dict[str, Any]]) -> None:
    st.title("Saved")
    st.caption("Material you marked as worth keeping.")
    if not rows:
        st.info("Nothing saved yet.")
        return
    for row in rows:
        render_source_card(row)


def render_metrics(rows: list[dict[str, Any]]) -> None:
    analyzed = sum(1 for row in rows if first_analysis(row))
    saved = sum(1 for row in rows if row.get("saved"))
    unread = sum(1 for row in rows if row.get("user_status") == "unread")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Items", len(rows))
    c2.metric("Analyzed", analyzed)
    c3.metric("Unread", unread)
    c4.metric("Saved", saved)


def render_empty_items_help() -> None:
    st.info("No items found for the current filters.")
    try:
        total = fetch_source_count()
    except Exception as exc:
        st.warning(f"Could not run source item count: {exc}")
        total = None

    if total is not None:
        st.caption(f"Visible source_items rows with the current Supabase key: {total}")

    if total == 0 and db_configured():
        st.warning(
            "The dashboard is connected through SUPABASE_DB_URL, and that database "
            "currently has 0 rows in public.source_items. Check that the database "
            "connection string belongs to the same project shown in Supabase SQL Editor."
        )
    elif total == 0 and using_service_role_key():
        project_url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL") or "unknown"
        st.warning(
            "The dashboard is using a service-role key, so this is not an RLS issue. "
            f"The connected project has 0 rows in public.source_items. Connected URL: {project_url}. "
            "Check that GitHub Actions writes to this same Supabase project, or run the collector "
            "workflow again with sink=supabase."
        )
    elif not using_service_role_key():
        st.warning(
            "The dashboard is using a publishable/anon key. If Supabase has rows but this "
            "count is 0, Row Level Security or API permissions are hiding them. For local "
            "internal use, add SUPABASE_SERVICE_ROLE_KEY to .env.local or paste it in "
            "Connect Supabase."
        )


def render_source_card(row: dict[str, Any]) -> None:
    analysis = first_analysis(row)
    source = source_label(row)
    status = str(row.get("user_status") or "unread")
    saved = bool(row.get("saved"))
    title = str(row.get("title") or "Untitled")

    with st.container(border=True):
        top = st.columns([0.72, 0.14, 0.14])
        with top[0]:
            st.subheader(title)
            st.caption(f"{source} · {row.get('topic_id', '')} · {row.get('published_at') or row.get('collected_at')}")
        with top[1]:
            new_status = st.selectbox(
                "Status",
                STATUSES,
                index=STATUSES.index(status) if status in STATUSES else 0,
                key=f"status-{row['id']}",
            )
        with top[2]:
            new_saved = st.toggle("Saved", value=saved, key=f"saved-{row['id']}")

        if new_status != status or new_saved != saved:
            update_item_state(
                int(row["id"]),
                user_status=new_status,
                saved=new_saved,
                mark_seen=True,
            )
            st.rerun()

        if analysis:
            score = analysis.get("learning_value")
            difficulty = analysis.get("difficulty") or "unknown"
            st.markdown(
                f"<span class='chip'>{escape(difficulty)}</span>"
                f"<span class='chip'>learning value <span class='score'>{score}</span></span>",
                unsafe_allow_html=True,
            )
            st.write(analysis.get("summary", ""))
            render_tags(analysis.get("tags", []))
            with st.expander("Highlights"):
                render_plain_bullets(analysis.get("highlights", []))
            with st.expander("Claims and follow-up questions"):
                st.markdown("**Claims**")
                render_plain_bullets(analysis.get("claims", []))
                st.markdown("**Questions**")
                render_plain_bullets(analysis.get("follow_up_questions", []))
        else:
            st.info("No AI analysis yet.")

        note = st.text_area("Personal note", value=str(row.get("user_note") or ""), key=f"note-{row['id']}")
        note_cols = st.columns([0.18, 0.82])
        with note_cols[0]:
            if st.button("Save note", key=f"save-note-{row['id']}"):
                update_item_state(int(row["id"]), user_note=note, mark_seen=True)
                st.success("Saved")
        with note_cols[1]:
            st.link_button("Open source", str(row.get("url") or "#"))


def first_analysis(row: dict[str, Any]) -> dict[str, Any]:
    analyses = row.get("source_item_analyses") or []
    if isinstance(analyses, list) and analyses:
        return analyses[0]
    if isinstance(analyses, dict):
        return analyses
    return {}


def source_label(row: dict[str, Any]) -> str:
    source = str(row.get("source") or "").title()
    community = row.get("community") or row.get("author") or ""
    return f"{source} / {community}" if community else source


def fetch_reader_rows(
    *,
    topic_id: str | None,
    status: str | None,
    saved: bool | None,
    limit: int,
) -> list[dict[str, Any]]:
    if db_configured():
        return fetch_reader_items_db(topic_id=topic_id, status=status, saved=saved, limit=limit)
    return fetch_reader_items(topic_id=topic_id, status=status, saved=saved, limit=limit)


def fetch_comparison_rows(topic_id: str | None, limit: int) -> list[dict[str, Any]]:
    if db_configured():
        return fetch_topic_comparisons_db(topic_id=topic_id, limit=limit)
    return fetch_topic_comparisons(topic_id=topic_id, limit=limit)


def fetch_source_count() -> int | None:
    if db_configured():
        return fetch_source_item_count_db()
    return fetch_source_item_count()


def update_item_state(
    item_id: int,
    *,
    user_status: str | None = None,
    saved: bool | None = None,
    user_note: str | None = None,
    mark_seen: bool = False,
) -> None:
    if db_configured():
        update_source_item_state_db(
            item_id,
            user_status=user_status,
            saved=saved,
            user_note=user_note,
            mark_seen=mark_seen,
        )
        return
    update_source_item_state(
        item_id,
        user_status=user_status,
        saved=saved,
        user_note=user_note,
        mark_seen=mark_seen,
    )


def render_tags(tags: list[Any]) -> None:
    html = "".join(f"<span class='chip'>{escape(tag)}</span>" for tag in tags or [])
    if html:
        st.markdown(html, unsafe_allow_html=True)


def render_bullets(items: list[Any], key: str) -> None:
    for item in items or []:
        if isinstance(item, dict):
            st.markdown(f"- {item.get(key, '')}")
        else:
            st.markdown(f"- {item}")


def render_plain_bullets(items: list[Any]) -> None:
    for item in items or []:
        st.markdown(f"- {item}")


def _env_status(name: str, *, secret: bool = False) -> None:
    exists = bool(os.getenv(name))
    label = "set" if exists else "missing"
    value = "******" if secret and exists else label
    st.caption(f"{name}: {value}")


def render_connection_form() -> None:
    missing_credentials = not (
        os.getenv("SUPABASE_URL")
        or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    ) or not (
        os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        or os.getenv("SUPABASE_ANON_KEY")
        or os.getenv("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY")
    )
    with st.expander("Connect Supabase", expanded=missing_credentials):
        current_url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL") or ""
        current_key = (
            os.getenv("SUPABASE_SERVICE_ROLE_KEY")
            or os.getenv("SUPABASE_ANON_KEY")
            or os.getenv("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY")
            or ""
        )
        current_db_url = os.getenv("SUPABASE_DB_URL") or ""
        url = st.text_input("Supabase URL", value=current_url, placeholder="https://...supabase.co")
        key = st.text_input("Supabase key", value=current_key, type="password")
        db_url = st.text_input(
            "Database URL",
            value=current_db_url,
            type="password",
            placeholder="postgresql://postgres...@...supabase.com:5432/postgres",
        )
        if st.button("Use for this session"):
            if db_url:
                os.environ["SUPABASE_DB_URL"] = db_url
                st.success("Connected to Supabase database for this Streamlit session")
                st.rerun()
                return
            if url and key:
                os.environ["SUPABASE_URL"] = url
                if key.startswith("sb_secret_"):
                    os.environ["SUPABASE_SERVICE_ROLE_KEY"] = key
                    os.environ.pop("SUPABASE_ANON_KEY", None)
                else:
                    os.environ["SUPABASE_ANON_KEY"] = key
                st.success("Connected for this Streamlit session")
                st.rerun()
            else:
                st.warning("Enter both Supabase URL and key.")


def _project_ref(url: str) -> str:
    import re

    match = re.search(r"https?://([^.]+)\.supabase\.", url or "")
    return match.group(1) if match else ""


def render_connection_diagnostics() -> None:
    """Confirm which project/key the dashboard reads and whether the table has rows.

    Distinguishes 'table unreachable / missing' from 'connected but empty', so a
    project mismatch between the dashboard and GitHub Actions is easy to spot.
    """
    with st.expander("Test connection", expanded=False):
        url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL") or ""
        project_ref = _project_ref(url)

        using_db = db_configured()
        if using_db:
            mode = "Postgres (SUPABASE_DB_URL)"
        else:
            mode = "Data API (PostgREST)"

        st.caption(f"Mode: {mode}")
        st.caption(f"Project: {project_ref or 'unknown'}")
        if not using_db:
            st.caption(f"Key type: {active_key_kind()} (bypasses RLS: {key_bypasses_rls()})")

        if not st.button("Run connection test"):
            return

        try:
            total = fetch_source_count()
        except Exception as exc:
            st.error(f"Could not reach source_items: {exc}")
            st.caption(
                "A 404 / 'relation does not exist' means the table is missing in this "
                "project — run the migrations in supabase/migrations. Any other error "
                "usually means the URL or key is wrong."
            )
            return

        if total is None:
            st.warning("Connected, but the row count was unavailable.")
        elif total == 0:
            if not using_db and not key_bypasses_rls():
                st.warning(
                    f"Connected to project '{project_ref}' with a "
                    f"'{active_key_kind()}' key, which does NOT bypass Row Level "
                    "Security. If the Supabase SQL Editor shows rows but this is 0, RLS "
                    "is hiding them from the Data API. Fastest fix: paste your project's "
                    "Postgres connection string into the Database URL field above (reads "
                    "directly, like the SQL Editor). Or put your sb_secret_... key in "
                    "the Supabase key field."
                )
            else:
                st.warning(
                    f"Connected to project '{project_ref}' but source_items has 0 rows "
                    "here. If the SQL Editor shows rows, you are pointed at a different "
                    "project — line up the URL/connection string with that project ref."
                )
        else:
            st.success(
                f"Connected to project '{project_ref}'. source_items has {total} row(s)."
            )


def escape(value: Any) -> str:
    import html

    return html.escape(str(value or ""))


if __name__ == "__main__":
    main()
