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
from prism_collector.supabase import (
    SupabaseConfigError,
    fetch_reader_items,
    fetch_topic_comparisons,
    update_source_item_state,
)


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
        st.caption("Environment")
        _env_status("SUPABASE_URL")
        _env_status("SUPABASE_SERVICE_ROLE_KEY", secret=True)
        _env_status("SUPABASE_ANON_KEY", secret=True)

    selected_topic = None if topic_id == "all" else topic_id

    try:
        if view == "Debates":
            render_debates(selected_topic)
            return

        saved_filter = True if view == "Saved" else None
        rows = fetch_reader_items(
            topic_id=selected_topic,
            status=status,
            saved=saved_filter,
            limit=limit,
        )
    except SupabaseConfigError as exc:
        st.error(str(exc))
        st.info("Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY before running the app.")
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
        st.info("No items found for the current filters.")
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
        comparisons = fetch_topic_comparisons(topic_id=topic_id, limit=10)
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
            update_source_item_state(
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
                update_source_item_state(int(row["id"]), user_note=note, mark_seen=True)
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


def escape(value: Any) -> str:
    import html

    return html.escape(str(value or ""))


if __name__ == "__main__":
    main()
