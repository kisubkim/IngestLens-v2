"""LangGraph pipeline: intake -> profile -> strategy -> parse -> chunk -> embed.

Each node is wrapped so step start/finish/error events and Run.current_step are recorded uniformly.
"""

import asyncio
import time
import traceback
import weakref

from langgraph.graph import END, START, StateGraph

from ..agents.chunker import chunk
from ..agents.common import PipelineState
from ..agents.embedder import embed
from ..agents.intake import intake
from ..agents.parser import parse
from ..agents.profiler import profile
from ..agents.strategy import strategy
from ..db import session
from ..events import emit_event
from ..models import Run, now

STEPS = [("intake", intake), ("profile", profile), ("strategy", strategy), ("parse", parse), ("chunk", chunk), ("embed", embed)]
STEP_NAMES = [name for name, _ in STEPS]


def _wrap(name, fn):
    async def node(state: PipelineState) -> dict:
        run_id = state["run_id"]
        with session() as s:
            s.get(Run, run_id).current_step = name
        emit_event(run_id, "step_started", name, f"{name} started")
        t0 = time.perf_counter()
        out = await fn(state)
        emit_event(run_id, "step_finished", name, f"{name} finished", {"seconds": round(time.perf_counter() - t0, 2)})
        return out

    return node


def build_graph():
    g = StateGraph(PipelineState)
    for name, fn in STEPS:
        g.add_node(name, _wrap(name, fn))
    g.add_edge(START, STEP_NAMES[0])
    for a, b in zip(STEP_NAMES, STEP_NAMES[1:]):
        g.add_edge(a, b)
    g.add_edge(STEP_NAMES[-1], END)
    return g.compile()


graph = build_graph()
_tasks: dict[str, asyncio.Task] = {}
# One lock per event loop: runs execute one at a time in the order they were started (asyncio.Lock is FIFO).
_locks: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock]" = weakref.WeakKeyDictionary()


def _run_lock() -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    if loop not in _locks:
        _locks[loop] = asyncio.Lock()
    return _locks[loop]


async def run_pipeline(run_id: str, doc_id: str) -> None:
    """Wait in the queue (status stays `queued`), then execute. Cancelling while queued never starts the run."""
    try:
        async with _run_lock():
            await _execute(run_id, doc_id)
    except asyncio.CancelledError:
        with session() as s:
            run = s.get(Run, run_id)
            run.status, run.error, run.finished_at = "cancelled", "cancelled while queued", now()
        emit_event(run_id, "warning", None, "Run cancelled while queued")
        emit_event(run_id, "run_finished", None, "cancelled", {"status": "cancelled"})


async def _execute(run_id: str, doc_id: str) -> None:
    with session() as s:
        run = s.get(Run, run_id)
        run.status, run.started_at = "running", now()
    try:
        await graph.ainvoke({"run_id": run_id, "doc_id": doc_id})
        status, error = "succeeded", None
    except asyncio.CancelledError:
        # Worker threads already started finish in the background; their results are discarded.
        status, error = "cancelled", "cancelled by user"
        with session() as s:
            step = s.get(Run, run_id).current_step
        emit_event(run_id, "warning", step, "Run cancelled")
    except Exception as e:
        status, error = "failed", f"{type(e).__name__}: {e}"
        with session() as s:
            step = s.get(Run, run_id).current_step
        emit_event(run_id, "error", step, error, {"traceback": traceback.format_exc()[-4000:]})
    with session() as s:
        run = s.get(Run, run_id)
        run.status, run.error, run.finished_at = status, error, now()
    emit_event(run_id, "run_finished", None, status, {"status": status})


def start_run(run_id: str, doc_id: str) -> None:
    # In-process task; it waits in run_pipeline's FIFO lock until earlier runs finish.
    task = asyncio.create_task(run_pipeline(run_id, doc_id))
    _tasks[run_id] = task
    task.add_done_callback(lambda _: _tasks.pop(run_id, None))


def cancel_run(run_id: str) -> bool:
    task = _tasks.get(run_id)
    return bool(task and task.cancel())
