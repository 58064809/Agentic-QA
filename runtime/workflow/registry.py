from __future__ import annotations

import importlib
import inspect
from collections.abc import Callable
from pathlib import Path

from runtime.graph.state import QAWorkflowState

Handler = Callable[..., QAWorkflowState]


def import_handler(handler_path: str) -> Handler:
    module_name, _, attribute = handler_path.rpartition(".")
    if not module_name or not attribute:
        raise ValueError(f"handler 路径非法: {handler_path}")
    module = importlib.import_module(module_name)
    handler = getattr(module, attribute, None)
    if not callable(handler):
        raise ValueError(f"handler 不存在或不可调用: {handler_path}")
    return handler


def handler_accepts_repo_root(handler: Handler) -> bool:
    signature = inspect.signature(handler)
    return len(signature.parameters) >= 2


def call_handler(handler: Handler, state: QAWorkflowState, repo_root: Path) -> QAWorkflowState:
    if handler_accepts_repo_root(handler):
        result = handler(state, repo_root)
    else:
        result = handler(state)
    return result if isinstance(result, QAWorkflowState) else state
