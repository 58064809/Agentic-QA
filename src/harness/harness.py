from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from queue import Queue
from threading import Thread

from harness.budget import BudgetLimits
from harness.contracts import HarnessEvent, ReviewDecision, RunSnapshot, TaskRequest
from harness.engine import HarnessEngine
from harness.model import ModelGateway, model_gateway_from_env
from harness.registry import AgentRegistry, SkillRegistry, ToolRegistry
from harness.store import WorkspaceStore


class Harness:
    """Stable Python facade. LangGraph and other orchestration backends remain internal."""

    def __init__(
        self,
        repo_root: Path | str = ".",
        *,
        model_gateway: ModelGateway | None = None,
        budget_limits: BudgetLimits | None = None,
        agent_registry: AgentRegistry | None = None,
        skill_registry: SkillRegistry | None = None,
        tool_registry: ToolRegistry | None = None,
        tool_handlers: dict[str, object] | None = None,
    ) -> None:
        self.store = WorkspaceStore(repo_root)
        self.tools = tool_registry or ToolRegistry.builtin()
        self.skills = skill_registry or SkillRegistry.builtin()
        self.agents = agent_registry or AgentRegistry.builtin(
            skills=self.skills,
            tools=self.tools,
        )
        self._engine = HarnessEngine(
            store=self.store,
            agents=self.agents,
            skills=self.skills,
            tools=self.tools,
            model=model_gateway or model_gateway_from_env(),
            limits=budget_limits,
            tool_handlers=tool_handlers,
        )

    def run(self, request: TaskRequest) -> RunSnapshot:
        return self._engine.execute(request)

    def stream(self, request: TaskRequest) -> Iterator[HarnessEvent]:
        queue: Queue[HarnessEvent | BaseException | None] = Queue()

        def worker() -> None:
            try:
                self._engine.execute(request, emit=queue.put)
            except BaseException as exc:
                queue.put(exc)
            finally:
                queue.put(None)

        thread = Thread(target=worker, name="agentic-qa-harness", daemon=True)
        thread.start()
        while True:
            item = queue.get()
            if item is None:
                break
            if isinstance(item, BaseException):
                raise item
            yield item
        thread.join()

    def resume(
        self,
        run_id: str,
        decision: ReviewDecision | None = None,
    ) -> RunSnapshot:
        snapshot = self.store.load_snapshot(run_id)
        return self._engine.resume(snapshot, decision)

    def inspect(self, run_id: str) -> RunSnapshot:
        return self.store.load_snapshot(run_id)

    def init_workspace(self, workspace: str) -> Path:
        request = TaskRequest(workspace=workspace, goal="workspace validation")
        return self.store.init_workspace(request.workspace)
