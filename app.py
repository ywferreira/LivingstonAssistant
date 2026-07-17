"""Livingston Township Assistant — public Streamlit chat UI over the RAG index."""

import csv
import os
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from config import CHROMA_DIR, CLERK_PHONE, COLLECTION_NAME, PROJECT_DIR

load_dotenv(PROJECT_DIR / ".env")
FEEDBACK_LOG = PROJECT_DIR / "feedback_log.csv"

BASE_SYSTEM_PROMPT = (
    "You are the official AI assistant for Livingston Township, New Jersey. "
    "Answer residents' questions using ONLY the retrieved Township documents "
    "provided as context — never from outside knowledge. For every assertion, "
    "cite the source URL and document name inline, e.g. "
    "([Recycling](https://www.livingstonnj.org/289/Recycling)). "
    "When a question asks about a specific property or address (for example "
    "its zoning district, flood zone, or collection schedule), the documents "
    "will not name that address — do NOT treat this as unanswerable. Instead, "
    "point the resident to the official resource for looking it up (e.g. the "
    "Updated Zoning Map PDF, a schedule, or a lookup tool found in the "
    "context), link it, and briefly explain how to use it to find their "
    "answer. "
    "Only when the retrieved documents contain nothing relevant to the topic, "
    "respond exactly: 'I cannot find this information in the official "
    f"documents; please contact the Township Clerk at {CLERK_PHONE}.' "
    "Be concise and practical; when a form or permit is involved, link to it "
    "and list the prerequisite steps the documents describe."
)

st.set_page_config(page_title="Livingston Township Assistant", page_icon="🏛️")


# ------------------------------------------------------------- RAG plumbing
@st.cache_resource(show_spinner="Loading Township knowledge index ...")
def load_index():
    import chromadb
    from llama_index.core import VectorStoreIndex
    from llama_index.vector_stores.chroma import ChromaVectorStore

    from llm_config import get_embed_model

    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    collection = client.get_collection(COLLECTION_NAME)
    vector_store = ChromaVectorStore(chroma_collection=collection)
    return VectorStoreIndex.from_vector_store(vector_store, embed_model=get_embed_model())


def system_prompt() -> str:
    # F-05: resident personalization — prioritize the user's zone/address.
    profile = st.session_state.get("resident_profile", "").strip()
    if profile:
        return (
            BASE_SYSTEM_PROMPT
            + f" The resident has shared their location: '{profile}'. When answering "
            "questions about trash, recycling, or collection schedules, prioritize "
            "the schedule/zone that applies to that location if the documents "
            "distinguish zones."
        )
    return BASE_SYSTEM_PROMPT


def get_chat_engine():
    key = f"chat_engine::{st.session_state.get('resident_profile', '')}"
    if st.session_state.get("chat_engine_key") != key:
        from llm_config import get_llm

        st.session_state.chat_engine = load_index().as_chat_engine(
            chat_mode="context",
            llm=get_llm(),
            system_prompt=system_prompt(),
            similarity_top_k=5,
        )
        st.session_state.chat_engine_key = key
    return st.session_state.chat_engine


def format_sources(source_nodes) -> list[str]:
    """Deduped markdown links 'title (url)' from the retrieved chunks."""
    seen: dict[str, None] = {}
    for node in source_nodes:
        meta = node.metadata or {}
        url = meta.get("source_url")
        title = meta.get("doc_title") or meta.get("file_name") or "Township document"
        label = f"[{title}]({url})" if url else str(title)
        page = meta.get("source") or meta.get("page_label")
        if page and str(meta.get("file_path", "")).endswith(".pdf"):
            label += f" — page {page}"
        seen.setdefault(label)
    return list(seen)


# ---------------------------------------------------------------- feedback
def log_feedback(idx: int) -> None:
    rating = st.session_state.get(f"feedback_{idx}")
    if rating is None:
        return
    msgs = st.session_state.messages
    question = msgs[idx - 1]["content"] if idx > 0 else ""
    answer = msgs[idx]["content"]
    is_new = not FEEDBACK_LOG.exists()
    with FEEDBACK_LOG.open("a", newline="") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(["timestamp", "question", "answer", "rating"])
        writer.writerow(
            [
                datetime.now(timezone.utc).isoformat(),
                question,
                answer,
                "up" if rating == 1 else "down",
            ]
        )


# --------------------------------------------------------------------- app
def render_sidebar() -> None:
    with st.sidebar:
        st.subheader("Personalize (optional)")
        st.text_input(
            "Your street or neighborhood",
            key="resident_profile",
            help="Used only to prioritize the right trash/recycling schedule in answers. Not stored.",
        )
        st.divider()
        st.caption(
            "Answers come from documents on livingstonnj.org and always include "
            "source links. This is an unofficial assistant — for authoritative "
            f"answers contact Town Hall at {CLERK_PHONE}."
        )


def render_chat() -> None:
    st.title("🏛️ Livingston Township Assistant")
    st.caption("Ask about trash & recycling, permits, forms, the pool, and other Township services.")

    if not os.getenv("OPENAI_API_KEY"):
        st.error("OPENAI_API_KEY is not set. Copy `.env.example` to `.env` and add your key, then restart.")
        st.stop()
    if not CHROMA_DIR.exists():
        st.error("No knowledge index found. Run `python crawler.py` then `python ingest.py` first.")
        st.stop()

    if "messages" not in st.session_state:
        st.session_state.messages = []

    for i, msg in enumerate(st.session_state.messages):
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg["role"] == "assistant":
                if msg.get("sources"):
                    with st.expander("Sources"):
                        for src in msg["sources"]:
                            st.markdown(f"- {src}")
                st.feedback("thumbs", key=f"feedback_{i}", on_change=log_feedback, args=(i,))

    if question := st.chat_input("e.g. When is bulk item pickup? How do I get a pool badge?"):
        st.session_state.messages.append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.markdown(question)

        with st.chat_message("assistant"):
            with st.spinner("Searching Township documents ..."):
                response = get_chat_engine().chat(question)
            st.markdown(response.response)
            sources = format_sources(response.source_nodes)
            if sources:
                with st.expander("Sources"):
                    for src in sources:
                        st.markdown(f"- {src}")

        st.session_state.messages.append(
            {"role": "assistant", "content": response.response, "sources": sources}
        )
        st.rerun()  # re-render so the new message gets its feedback widget


render_sidebar()
render_chat()
