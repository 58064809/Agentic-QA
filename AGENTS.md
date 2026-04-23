# AGENTS.md

## Project Memory

This repository is a personal AI assistant for senior test engineering work.

It is not:
- a web platform
- a team collaboration system
- a large knowledge base
- a multi-agent discussion system
- a heavy enterprise orchestration framework

The assistant should work in PyCharm, Cursor, terminal, and later Feishu/WeCom integrations. Users speak in natural language, and the assistant identifies intent, loads the minimum needed rules/context, executes actions, returns results, and saves outputs by default.

## Core Principles

- Keep the structure lightweight.
- Keep rules short and atomic.
- Load context on demand.
- Put executable logic in Python.
- Keep `.md` and `.yaml` files as short instructions, rules, and flows.
- Prefer concrete output over architecture discussion.
- Do not create broad prompt-document systems or unnecessary agents.

## Directory Boundaries

- `AGENTS.md`: project-level memory and instructions for Codex/IDE sessions.
- `agents/`: role definitions. Keep one folder per agent, each with an `AGENT.md`.
- `rules/`: intent rules and routing config.
- `flows/`: lightweight flow definitions.
- `skills/`: skill instructions only. Each skill folder should contain `SKILL.md`.
- `actions/`: Python implementations used by skills.
- `runtime/`: assistant runtime, router, intent matching, discovery, formatting, and output saving.
- `workspace/requirements/`: local requirement packages.
- `tests/`: regression tests for real usage paths.

## Agent Strategy

Keep `agents/senior_test_engineer/AGENT.md` as the current default role.

Do not move that file to the repository root. The root `AGENTS.md` is project memory for Codex/IDE behavior, while `agents/*/AGENT.md` files are selectable assistant roles loaded by runtime routing.

If multiple agents are added later, use this shape:

```text
agents/
  senior_test_engineer/
    AGENT.md
  automation_engineer/
    AGENT.md
  release_checker/
    AGENT.md
```

Only add a new agent when it has a clearly different responsibility. Do not add multiple agents just to let them discuss with each other.

## Workspace Rules

Each requirement should have its own package:

```text
workspace/requirements/<requirement-name>/
  docs/
  prototype/
  logs/
  tests/
  outputs/
```

Real PRDs, prototypes, logs, generated outputs, and local test artifacts should stay local and should not be committed.

The assistant should prefer requirement-package-scoped discovery and save outputs under the matched package `outputs/` directory.

## Assistant Behavior

When the user says things like "帮我分析需求", "生成用例", "执行 pytest", or "分析日志", the assistant should:

1. Identify the intent.
2. Load the matching rule, flow, and skill instruction.
3. Discover the relevant requirement package when needed.
4. Read the minimum necessary PRD/prototype/log context.
5. Execute the mapped Python action.
6. Return a concise human-readable result.
7. Save the full result by default.

## Current Priority

Make the assistant useful for daily personal testing work:

- Professional requirement analysis.
- Executable test case tables.
- Smarter pytest execution.
- Practical log analysis.
- Later extensions: read-only DB query, Feishu notification, WeCom notification.

## Known Gaps

These are accepted current limitations and should guide future work:

- Intent recognition is still rule-based and brittle. It needs better scoring, negative signals, ambiguity handling, and possibly a lightweight LLM fallback later.
- Flows are lightweight execution traces, not a heavy orchestration framework. Keep them small, but ensure each runtime step is recorded and debuggable.
- Action input/output should follow the `ActionResult` protocol. Existing actions may still expose domain fields directly for formatters, but protocol metadata should be preserved.
- Pytest execution is still basic. Improve target discovery, marker validation, collection-only preview, rerun behavior, timeout handling, and environment diagnostics.
- Pytest result analysis is currently evidence-based classification, not full root-cause analysis. Improve by extracting failing node IDs, assertion diffs, fixture/setup failures, dependency errors, and linking log clues.

## Borrowed QA Automation Standards

Useful ideas are adapted from `fugazi/test-automation-skills-agents`, but this project must not become a copied knowledge base.

Apply these standards when generating or reviewing tests:

- Prefer risk-based planning and test design techniques: equivalence classes, boundary values, decision tables, state transitions, and scenario testing.
- API tests should cover status codes, auth/permission failures, schema/contract checks, pagination/filtering/sorting, idempotency, and invalid payloads.
- Playwright tests should use stable locators, web-first assertions, `test.step`, trace/screenshots/video on failure, and avoid hard waits.
- Flaky test triage should look for timing, environment differences, shared state, race conditions, browser differences, and retry-only passes.
- Avoid anti-patterns: happy-path-only coverage, brittle selectors, hard waits, shared mutable state, over-mocking, implementation-detail assertions, and missing schema validation.
