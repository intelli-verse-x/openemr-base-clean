from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any


class TargetClient:
    def __init__(self, base_url: str, timeout_s: float = 60.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s

    def ready(self) -> dict[str, Any]:
        return self._request("GET", "/ready")

    def chat(self, body: dict[str, Any]) -> tuple[int, dict[str, Any], int]:
        return self._request_status("POST", "/chat", body)

    def w2_chat(self, body: dict[str, Any]) -> tuple[int, dict[str, Any], int]:
        return self._request_status("POST", "/w2/chat", body)

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        status, data, _ = self._request_status(method, path, body)
        if status >= 400:
            raise RuntimeError(f"TargetUnreachableOrError status={status} body={data}")
        return data

    def _request_status(
        self, method: str, path: str, body: dict[str, Any] | None = None
    ) -> tuple[int, dict[str, Any], int]:
        url = f"{self.base_url}{path}"
        data = None
        headers = {"Accept": "application/json"}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                raw = resp.read().decode("utf-8")
                status = resp.status
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", errors="replace")
            status = e.code
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"TargetUnreachable: {e}") from e
        latency_ms = int((time.time() - t0) * 1000)
        try:
            parsed: dict[str, Any] = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            parsed = {"raw": raw[:2000]}
        return status, parsed, latency_ms
