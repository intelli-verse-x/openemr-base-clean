from __future__ import annotations

import os
from dataclasses import dataclass


DEFAULT_TARGET = "https://clinical-copilot.intelli-verse-x.ai"


@dataclass(frozen=True)
class Settings:
    target_base_url: str
    allowlist: tuple[str, ...]
    budget_usd: float
    max_mutations: int
    timeout_s: float

    @classmethod
    def from_env(cls) -> "Settings":
        target = os.getenv("TARGET_BASE_URL", DEFAULT_TARGET).rstrip("/")
        raw = os.getenv(
            "TARGET_ALLOWLIST",
            "https://clinical-copilot.intelli-verse-x.ai,http://127.0.0.1:8080,http://localhost:8080",
        )
        allow = tuple(x.strip().rstrip("/") for x in raw.split(",") if x.strip())
        return cls(
            target_base_url=target,
            allowlist=allow,
            budget_usd=float(os.getenv("ADV_BUDGET_USD", "2.0")),
            max_mutations=int(os.getenv("ADV_MAX_MUTATIONS", "3")),
            timeout_s=float(os.getenv("ADV_TIMEOUT_S", "60")),
        )

    def assert_allowlisted(self, url: str | None = None) -> str:
        base = (url or self.target_base_url).rstrip("/")
        if base not in self.allowlist:
            raise PermissionError(f"AllowlistDenied: {base} not in TARGET_ALLOWLIST")
        return base
