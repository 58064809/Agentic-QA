from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def disable_real_llm_by_default(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
