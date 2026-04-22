from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]


def load_routing() -> dict:
    routing_file = ROOT / 'rules' / 'routing.yaml'
    return yaml.safe_load(routing_file.read_text(encoding='utf-8'))


def route_intent(intent_name: str) -> dict:
    routing = load_routing()
    return routing['intents'][intent_name]


if __name__ == '__main__':
    print(load_routing())
