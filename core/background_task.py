"""Avbrytbart bakgrundsarbete (förslag 9), utan Qt-beroenden.

Modulen innehåller själva logiken: en avbrytningstoken, en rapportör som bara
skickar ändrade lägen vidare och en körfunktion som fångar fel. GUI-lagret kör
dessa funktioner i en tråd och ritar förloppet på GUI-tråden.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

_log = logging.getLogger(__name__)

PROGRESS_MIN_INTERVAL = 0.05


class TaskCancelled(Exception):
    """Arbetet avbröts av användaren; ingenting får då ha skrivits."""


class CancellationToken:
    def __init__(self) -> None:
        self._event = threading.Event()
        self._lock = threading.Lock()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        if self._event.is_set():
            raise TaskCancelled("Arbetet avbröts")


class ProgressReporter:
    """Skickar (aktuell, total, text) vidare, men sparsamt och utan GUI-beroende."""

    def __init__(self, emit: Callable[[int, int, str], None] | None = None,
                 token: CancellationToken | None = None,
                 min_interval: float = PROGRESS_MIN_INTERVAL,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._emit_callback = emit
        self._token = token
        self._min_interval = max(0.0, float(min_interval))
        self._clock = clock
        self._last = 0.0
        self._emitted = False
        self._last_payload: tuple[int, int, str] | None = None

    @property
    def token(self) -> CancellationToken | None:
        return self._token

    def emit(self, current: int, total: int, message: str = "", *,
             force: bool = False) -> None:
        if self._token is not None:
            self._token.raise_if_cancelled()
        payload = (int(current), int(total), str(message))
        now = self._clock()
        if not force and payload == self._last_payload:
            return
        if (not force and self._emitted and self._min_interval
                and now - self._last < self._min_interval):
            return
        self._last = now
        self._emitted = True
        self._last_payload = payload
        if self._emit_callback is not None:
            self._emit_callback(*payload)


def run(work: Callable[..., Any], *,
        token: CancellationToken | None = None,
        progress: Callable[[int, int, str], None] | None = None) -> dict:
    """Kör work(progress) och returnera alltid ett resultat, även vid fel.

    Arbetet får inte röra Qt-widgets. Vid avbrott returneras cancelled=True och
    work ansvarar för att inga ändringar hunnit skrivas (läsning får avbrytas).
    """
    token = token or CancellationToken()
    reporter = ProgressReporter(progress, token)
    started = time.monotonic()
    try:
        token.raise_if_cancelled()
        value = work(reporter)
    except TaskCancelled:
        return {"ok": False, "cancelled": True, "value": None, "error": None,
                "seconds": round(time.monotonic() - started, 3)}
    except Exception as exc:  # noqa: BLE001 - felet visas för användaren
        _log.exception("Bakgrundsarbetet misslyckades")
        return {"ok": False, "cancelled": False, "value": None, "error": exc,
                "seconds": round(time.monotonic() - started, 3)}
    return {"ok": True, "cancelled": False, "value": value, "error": None,
            "seconds": round(time.monotonic() - started, 3)}


def chunked(iterable, size: int):
    """Dela upp ett arbete i lagom stora steg så avbrott hinner upptäckas."""
    if size <= 0:
        raise ValueError("Stegstorleken måste vara större än noll")
    batch = []
    for item in iterable:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch
