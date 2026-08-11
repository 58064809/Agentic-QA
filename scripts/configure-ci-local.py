from __future__ import annotations

import argparse
import base64
import os
from pathlib import Path

import yaml

SECRET_REFERENCES = {
    ("postgres", "password"): "secret://postgres.password",
    ("runtime", "cleanup_journal_key"): "secret://runtime.cleanup_journal_key",
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Populate CI-only values in the local SecretProvider storage."
    )
    parser.add_argument("--profile", choices=("ci", "nightly"), required=True)
    parser.add_argument("--config", default="agentic-qa.local.yml")
    return parser.parse_args()


def _require_secret_references(payload: dict[str, object]) -> None:
    for path, expected in SECRET_REFERENCES.items():
        value: object = payload
        for segment in path:
            if not isinstance(value, dict):
                raise SystemExit(f"invalid local config at {'.'.join(path)}")
            value = value.get(segment)
        if value != expected:
            raise SystemExit(
                f"refusing to overwrite business field {'.'.join(path)}; expected {expected}"
            )


def main() -> int:
    args = _parse_args()
    path = Path(args.config)
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit("local config must be a YAML mapping")
    _require_secret_references(payload)
    descriptor = payload.get("secrets")
    if not isinstance(descriptor, dict) or descriptor.get("provider") != "local":
        raise SystemExit("CI bootstrap requires the local SecretProvider")
    values = descriptor.get("values")
    if not isinstance(values, dict):
        raise SystemExit("secrets.values must be a mapping")

    values["postgres.password"] = "postgres" if args.profile == "ci" else "nightly-unused"
    values["runtime.cleanup_journal_key"] = base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")
    values["api.member-service.dev.auth.login.phone"] = "13500000000"
    values["api.member-service.dev.auth.login.sms_code"] = "000000"
    values["api.member-service.dev.auth.login.encryption.key"] = "ci-only-aes-key!"
    values["api.member-service.dev.auth.fallback_token"] = ""

    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
