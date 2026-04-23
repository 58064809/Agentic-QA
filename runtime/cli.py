from __future__ import annotations

import json
import sys
from pathlib import Path

from runtime.assistant import PersonalAITestAssistant


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("Usage: python -m runtime.cli <request> [workspace_root] [--json]")
        return 1

    output_json = "--json" in args
    clean_args = [arg for arg in args if arg != "--json"]
    request = clean_args[0]
    workspace_root = Path(clean_args[1]) if len(clean_args) > 1 else None
    assistant = PersonalAITestAssistant(workspace_root=workspace_root)
    result = assistant.handle(request)
    if output_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(result.get("formatted_output") or json.dumps(result, ensure_ascii=False, indent=2))
        saved_files = result.get("saved_output", {}).get("files", [])
        if saved_files:
            print("\n---")
            print("Saved output:")
            for file_info in saved_files:
                print(file_info["path"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
