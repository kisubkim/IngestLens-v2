"""Run event log + fan-out to SSE subscribers.

Agents call emit_event()/record_decision() from the event loop or from worker threads.
Every event is persisted first, so a late SSE subscriber can replay the full history.
"""

import asyncio
from collections import defaultdict

from .db import session
from .models import Decision, Event, to_dict


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self, run_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._subs[run_id].add(q)
        return q

    def unsubscribe(self, run_id: str, q: asyncio.Queue) -> None:
        self._subs[run_id].discard(q)
        if not self._subs[run_id]:
            del self._subs[run_id]

    def publish(self, run_id: str, payload: dict) -> None:
        loop = self._loop
        if loop is None:
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            self._fanout(run_id, payload)
        else:
            loop.call_soon_threadsafe(self._fanout, run_id, payload)

    def _fanout(self, run_id: str, payload: dict) -> None:
        for q in list(self._subs.get(run_id, ())):
            q.put_nowait(payload)


bus = EventBus()


def emit_event(run_id: str, type: str, step: str | None = None, message: str = "", data: dict | None = None) -> dict:
    with session() as s:
        ev = Event(run_id=run_id, type=type, step=step, message=message, data=data or {})
        s.add(ev)
        s.flush()
        payload = to_dict(ev)
    bus.publish(run_id, payload)
    return payload


def record_decision(
    run_id: str,
    step: str,
    subject: str,
    choice: str,
    *,
    rule_id: str | None = None,
    inputs: dict | None = None,
    alternatives: list | None = None,
    confidence: float | None = None,
    reasoning: str = "",
) -> dict:
    with session() as s:
        d = Decision(
            run_id=run_id,
            step=step,
            subject=subject,
            choice=choice,
            rule_id=rule_id,
            inputs=inputs or {},
            alternatives=alternatives or [],
            confidence=confidence,
            reasoning=reasoning,
        )
        s.add(d)
        s.flush()
        payload = to_dict(d)
    emit_event(run_id, "decision", step, f"{subject}: {choice}", payload)
    return payload
