"""API-Football v3 client: cached, quota-aware and polite.

* Every successful response is saved under RAW_DIR/api_football/ and reused forever,
  so the same request is never paid for twice.
* A run stops cleanly when its own request cap is reached, or when the daily
  quota left (from the response headers) falls to the reserve.
* Requests are spaced out to stay under the per-minute limit.
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE_URL = "https://v3.football.api-sports.io"


class BudgetExhausted(Exception):
    """No more live requests allowed in this run (cap reached or daily quota low)."""


class PlanRestricted(Exception):
    """The free plan refused the request (e.g. page > 3)."""


class ApiError(Exception):
    """Any other error reported by the API."""


class ApiFootballClient:
    def __init__(
        self,
        api_key: str,
        cache_dir: Path,
        max_requests: int = 80,
        reserve: int = 5,
        min_interval_s: float = 6.5,
        session: requests.Session | None = None,
        sleep=time.sleep,
    ):
        if not api_key:
            raise ValueError("API_FOOTBALL_KEY is not set")
        self.api_key = api_key
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_requests = max_requests
        self.reserve = reserve
        self.min_interval_s = min_interval_s
        self.session = session or requests.Session()
        self.sleep = sleep
        self.live_requests = 0
        self.daily_remaining: int | None = None
        self._last_call = 0.0

    # ---------- cache ----------
    def cache_path(self, endpoint: str, params: dict) -> Path:
        key = "_".join(f"{k}-{params[k]}" for k in sorted(params))
        return self.cache_dir / f"{endpoint.replace('/', '-')}__{key}.json"

    def cached(self, endpoint: str, params: dict) -> dict | None:
        path = self.cache_path(endpoint, params)
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))["body"]
        return None

    # ---------- requests ----------
    def get(self, endpoint: str, params: dict) -> dict:
        """Return the response body, from cache if present, otherwise from the API."""
        body = self.cached(endpoint, params)
        if body is not None:
            return body
        return self._live_get(endpoint, params, retry_on_rate_limit=True)

    def _check_budget(self) -> None:
        if self.live_requests >= self.max_requests:
            raise BudgetExhausted(f"run cap of {self.max_requests} requests reached")
        if self.daily_remaining is not None and self.daily_remaining <= self.reserve:
            raise BudgetExhausted(f"daily quota low ({self.daily_remaining} left, reserve {self.reserve})")

    def _live_get(self, endpoint: str, params: dict, retry_on_rate_limit: bool) -> dict:
        self._check_budget()
        wait = self.min_interval_s - (time.monotonic() - self._last_call)
        if self._last_call and wait > 0:
            self.sleep(wait)

        resp = self.session.get(
            f"{BASE_URL}/{endpoint}", headers={"x-apisports-key": self.api_key}, params=params, timeout=30
        )
        self._last_call = time.monotonic()
        self.live_requests += 1
        remaining = resp.headers.get("x-ratelimit-requests-remaining")
        if remaining is not None and str(remaining).lstrip("-").isdigit():
            self.daily_remaining = int(remaining)

        if resp.status_code == 429:
            return self._rate_limited(endpoint, params, retry_on_rate_limit)
        resp.raise_for_status()
        body = resp.json()

        errors = body.get("errors") or {}
        if errors:
            text = json.dumps(errors)
            if isinstance(errors, dict) and "rateLimit" in errors:
                return self._rate_limited(endpoint, params, retry_on_rate_limit)
            if isinstance(errors, dict) and "requests" in errors:
                self.daily_remaining = 0
                raise BudgetExhausted(f"daily request limit reached: {text}")
            if isinstance(errors, dict) and "plan" in errors:
                raise PlanRestricted(text)
            raise ApiError(text)

        self.cache_path(endpoint, params).write_text(
            json.dumps(
                {"fetched_at": datetime.now(timezone.utc).isoformat(), "endpoint": endpoint,
                 "params": params, "body": body},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return body

    def _rate_limited(self, endpoint: str, params: dict, retry: bool) -> dict:
        if not retry:
            raise ApiError("per-minute rate limit hit twice in a row")
        self.sleep(61)
        return self._live_get(endpoint, params, retry_on_rate_limit=False)
