"""Quota-aware limiter: RPM + TPM sliding windows and a persisted daily (RPD) counter.

Every LLM, judge and embedding call goes through Limiter.acquire(). Quota days reset at midnight Pacific.
"""

from __future__ import annotations

import datetime as dt
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable
from zoneinfo import ZoneInfo

from flightrec.config import norm_model

PT = ZoneInfo("America/Los_Angeles")
IST = ZoneInfo("Asia/Kolkata")


class QuotaExhausted(Exception):
    def __init__(self, model, resume_at):
        self.model, self.resume_at = model, resume_at
        super().__init__(f"daily quota exhausted for {model}; resume after {resume_at.astimezone(IST):%Y-%m-%d %H:%M} IST")


def next_reset(now_pt: dt.datetime | None = None) -> dt.datetime:
    today = (now_pt or dt.datetime.now(PT)).date()
    return dt.datetime.combine(today + dt.timedelta(days=1), dt.time(0, 0), PT)


class Limiter:
    SAFETY = 0.9
    FREE_PREFIXES = ("ollama", "fake-")

    def __init__(self, store, limits: dict, *, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep,
                 now_pt: Callable[[], dt.datetime] = lambda: dt.datetime.now(PT)):
        self.store, self.limits = store, {norm_model(k): v for k, v in limits.items()}
        self.clock, self.sleep, self.now_pt = clock, sleep, now_pt
        self.win: dict[str, deque] = defaultdict(deque)  # model -> deque[(monotonic_ts, tokens)]
        self._lock = threading.Lock()

    def acquire(self, model: str, est_tokens: int = 0) -> float:
        """Block until a call to `model` fits the RPM/TPM windows; returns seconds waited.

        Raises KeyError for models missing from limits.yaml, ValueError when one request exceeds the TPM
        budget, QuotaExhausted when the (safety-scaled) daily limit is reached.
        """
        model = norm_model(model)
        if model.startswith(self.FREE_PREFIXES):
            return 0.0
        lim = self.limits[model]  # KeyError => refuse: model not in limits.yaml
        rpm, tpm = int(lim["rpm"] * self.SAFETY), int(lim["tpm"] * self.SAFETY)
        if est_tokens > tpm:
            raise ValueError(f"single request exceeds TPM budget ({est_tokens} > {tpm}) for {model}")
        with self._lock:
            now_pt = self.now_pt()
            today = now_pt.date()
            if self.store.calls(today, model) >= int(lim["rpd"] * self.SAFETY):
                raise QuotaExhausted(model, next_reset(now_pt))
            waited, w = 0.0, self.win[model]
            while True:
                now = self.clock()
                while w and now - w[0][0] >= 60:
                    w.popleft()
                if len(w) < rpm and sum(t for _, t in w) + est_tokens <= tpm:
                    break
                sleep = 60 - (now - w[0][0]) + 0.05
                self.sleep(sleep)
                waited += sleep
            w.append((self.clock(), est_tokens))
            self.store.increment(today, model)  # counted before the call; retries count too
            return waited
