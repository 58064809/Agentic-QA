from __future__ import annotations

from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]


def load_flow(flow_name: str) -> dict:
    flow_file = ROOT / 'flows' / f'{flow_name}.yaml'
    return yaml.safe_load(flow_file.read_text(encoding='utf-8'))
