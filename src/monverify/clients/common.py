from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)


class APIRequestError(RuntimeError):
    """Safe, structured error for an HTTP API response."""

    def __init__(self, message: str, *, status_code: int | None = None, url: str | None = None, detail: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.url = url
        self.detail = detail


def cache_key(prefix: str, payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()[:20]
    return f"{prefix}_{digest}.json"


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _response_detail(response: requests.Response) -> str | None:
    """Return a short server error message without request headers or secrets."""
    try:
        payload = response.json()
        if isinstance(payload, dict):
            for key in ("message", "error", "error-message", "service-error"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()[:500]
                if isinstance(value, dict):
                    text = value.get("statusText") or value.get("message") or value.get("status")
                    if text:
                        return str(text).strip()[:500]
    except (ValueError, TypeError):
        pass
    text = (response.text or "").strip()
    return text[:500] if text else None


def request_json(
    session: requests.Session,
    method: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 60.0,
    max_attempts: int = 5,
) -> tuple[dict[str, Any], requests.Response]:
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = session.request(method, url, params=params, headers=headers, timeout=timeout)

            # Authentication/authorization and most client errors are permanent for
            # this request. Do not hammer the API by retrying them.
            if 400 <= response.status_code < 500 and response.status_code not in {408, 429}:
                detail = _response_detail(response)
                raise APIRequestError(
                    f"HTTP {response.status_code} returned by API",
                    status_code=response.status_code,
                    url=url,
                    detail=detail,
                )

            if response.status_code in {408, 429} or 500 <= response.status_code < 600:
                if attempt == max_attempts:
                    detail = _response_detail(response)
                    raise APIRequestError(
                        f"HTTP {response.status_code} returned by API after {max_attempts} attempts",
                        status_code=response.status_code,
                        url=url,
                        detail=detail,
                    )
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

        except APIRequestError:
            raise
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            if attempt == max_attempts:
                break
            delay = min(2 ** (attempt - 1), 30)
            logger.warning("Request failed (%s); retrying in %.1fs", exc, delay)
            time.sleep(delay)

    raise RuntimeError(f"Request failed after {max_attempts} attempts: {url}") from last_error
