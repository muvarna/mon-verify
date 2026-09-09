from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)


def cache_key(prefix: str, payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()[:20]
    return f"{prefix}_{digest}.json"


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def request_json(session: requests.Session, method: str, url: str, *, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None, timeout: float = 60.0, max_attempts: int = 5) -> tuple[dict[str, Any], requests.Response]:
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = session.request(method, url, params=params, headers=headers, timeout=timeout)
            if response.status_code == 429 or 500 <= response.status_code < 600:
                if attempt == max_attempts:
                    response.raise_for_status()
                retry_after = response.headers.get("Retry-After")
                try:
                    delay = float(retry_after) if retry_after else min(2 ** (attempt - 1), 30)
                except ValueError:
                    delay = min(2 ** (attempt - 1), 30)
                logger.warning("HTTP %s from %s; retrying in %.1fs", response.status_code, url, delay)
                time.sleep(delay)
                continue
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError(f"Expected JSON object from {url}")
            return payload, response
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            if attempt == max_attempts:
                break
            delay = min(2 ** (attempt - 1), 30)
            logger.warning("Request failed (%s); retrying in %.1fs", exc, delay)
            time.sleep(delay)
    raise RuntimeError(f"Request failed after {max_attempts} attempts: {url}") from last_error
