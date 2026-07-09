from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from langgraph.store.memory import InMemoryStore  # noqa: E402

from runtime.session.manager import SessionManager  # noqa: E402
from runtime.session.store import SessionMetadata, SessionStore  # noqa: E402


def test_session_store_persists_metadata_in_langgraph_store(tmp_path: Path) -> None:
    store = SessionStore(tmp_path, store=InMemoryStore())
    metadata = SessionMetadata.new("demo")
    metadata.last_intent = "testcase_generation"

    store.save_metadata(metadata)
    loaded = store.load_metadata("demo")

    assert loaded is not None
    assert loaded.session_id == "demo"
    assert loaded.thread_id == metadata.thread_id
    assert loaded.last_intent == "testcase_generation"
    assert store.session_exists("demo")


def test_session_store_history_uses_langgraph_store_without_jsonl(tmp_path: Path) -> None:
    store = SessionStore(tmp_path, store=InMemoryStore())
    metadata = SessionMetadata.new("demo")
    store.save_metadata(metadata)

    store.append_history("demo", "user", "hello")
    metadata.history_count += 1
    store.save_metadata(metadata)
    store.append_history("demo", "assistant", "world")

    history = store.load_history("demo", max_lines=2)

    assert [item["role"] for item in history] == ["user", "assistant"]
    assert [item["content"] for item in history] == ["hello", "world"]


def test_session_manager_reset_deletes_langgraph_store_session(tmp_path: Path) -> None:
    backing_store = InMemoryStore()
    manager = SessionManager(tmp_path, store=backing_store)
    session = manager.get_or_create("demo")
    session.append_history("user", "hello")

    reset = manager.reset("demo")

    assert reset.session_id == "demo"
    assert reset.thread_id != session.thread_id
    assert reset.load_history() == []
    assert manager.exists("demo")
