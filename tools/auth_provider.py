from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.secret_store import SecretStore


@dataclass(frozen=True)
class AuthToken:
    value: str
    token_type: str = "Bearer"
    expires_at: float = 0

    @property
    def expired(self) -> bool:
        return bool(self.expires_at) and time.time() >= self.expires_at - 30


class AuthProvider:
    def __init__(self, secret_store: SecretStore | None = None, cache_file: str | Path | None = None) -> None:
        self.secret_store = secret_store or SecretStore()
        self.cache_file = Path(cache_file) if cache_file else Path.home() / ".ai-assistant" / "token_cache.json"

    def auth_headers(self, profile: str | dict[str, Any] | None = None) -> dict[str, str]:
        token = self.get_token(profile)
        if not token.value:
            return {}
        if token.token_type.lower() == "cookie":
            return {"Cookie": token.value}
        return {"Authorization": f"{token.token_type} {token.value}"}

    def get_token(self, profile: str | dict[str, Any] | None = None) -> AuthToken:
        config = self._normalize_profile(profile)
        plain_token = config.get("token")
        if plain_token:
            return AuthToken(value=str(plain_token), token_type=str(config.get("token_type") or "Bearer"))

        env_name = config.get("token_env") or "TEST_AUTH_TOKEN"
        value = self.secret_store.get(str(env_name))
        if value:
            return AuthToken(value=value, token_type=str(config.get("token_type") or "Bearer"))

        cached = self._load_cache().get(str(config.get("name") or "default"))
        if cached:
            token = AuthToken(
                value=str(cached.get("value", "")),
                token_type=str(cached.get("token_type") or "Bearer"),
                expires_at=float(cached.get("expires_at") or 0),
            )
            if token.value and not token.expired:
                return token
        return AuthToken(value="")

    def save_token(self, profile_name: str, token: AuthToken) -> None:
        data = self._load_cache()
        data[profile_name] = {
            "value": token.value,
            "token_type": token.token_type,
            "expires_at": token.expires_at,
        }
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        self.cache_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_cache(self) -> dict[str, Any]:
        if not self.cache_file.exists():
            return {}
        return json.loads(self.cache_file.read_text(encoding="utf-8"))

    def _normalize_profile(self, profile: str | dict[str, Any] | None) -> dict[str, Any]:
        if profile is None:
            return {}
        if isinstance(profile, str):
            return {"name": profile, "token_env": profile}
        return dict(profile)
