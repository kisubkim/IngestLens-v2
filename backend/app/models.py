import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def _id() -> str:
    return uuid.uuid4().hex


def now() -> datetime:
    return datetime.now(timezone.utc)


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    filename: Mapped[str] = mapped_column(String(512))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    size: Mapped[int] = mapped_column(Integer)
    path: Mapped[str] = mapped_column(String(1024))
    format: Mapped[str | None] = mapped_column(String(32))
    pdf_path: Mapped[str | None] = mapped_column(String(1024))
    page_count: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="queued")  # queued/running/succeeded/failed/cancelled
    current_step: Mapped[str | None] = mapped_column(String(32))
    error: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)  # profile, plan, per-step stats
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Event(Base):
    __tablename__ = "run_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    type: Mapped[str] = mapped_column(String(32))  # step_started/step_finished/progress/decision/warning/error/run_finished
    step: Mapped[str | None] = mapped_column(String(32))
    message: Mapped[str] = mapped_column(Text, default="")
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class Decision(Base):
    __tablename__ = "decisions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    step: Mapped[str] = mapped_column(String(32))
    subject: Mapped[str] = mapped_column(String(128))  # "document", "page 12", "chunking" ...
    choice: Mapped[str] = mapped_column(String(256))
    rule_id: Mapped[str | None] = mapped_column(String(64))
    inputs: Mapped[dict] = mapped_column(JSON, default=dict)  # feature values the decision used
    alternatives: Mapped[list] = mapped_column(JSON, default=list)  # [{choice, reason_rejected}]
    confidence: Mapped[float | None] = mapped_column(Float)
    reasoning: Mapped[str] = mapped_column(Text, default="")


class PageProfile(Base):
    __tablename__ = "page_profiles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    page: Mapped[int] = mapped_column(Integer)  # 0-based
    label: Mapped[str] = mapped_column(String(32))
    rule_id: Mapped[str] = mapped_column(String(64))
    confidence: Mapped[float] = mapped_column(Float)
    features: Mapped[dict] = mapped_column(JSON, default=dict)
    parser: Mapped[str | None] = mapped_column(String(32))


class Element(Base):
    __tablename__ = "elements"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    page: Mapped[int] = mapped_column(Integer)
    seq: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(16))  # text/title/table/figure
    bbox: Mapped[list] = mapped_column(JSON)
    content: Mapped[str] = mapped_column(Text)
    source_tool: Mapped[str] = mapped_column(String(32))
    meta: Mapped[dict | None] = mapped_column(JSON, default=dict)  # figure_type, caption, region source, vlm seconds...


class Chunk(Base):
    __tablename__ = "chunks"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    tokens: Mapped[int] = mapped_column(Integer)
    pages: Mapped[list] = mapped_column(JSON)
    bboxes: Mapped[list] = mapped_column(JSON)  # [{page, bbox}]
    section: Mapped[str | None] = mapped_column(String(256))
    element_types: Mapped[list] = mapped_column(JSON)
    strategy_id: Mapped[str] = mapped_column(String(32))
    embedded: Mapped[bool] = mapped_column(Boolean, default=False)


def to_dict(obj) -> dict:
    out = {}
    for col in obj.__table__.columns:
        v = getattr(obj, col.name)
        if isinstance(v, datetime):
            # SQLite returns naive datetimes; values are always stored in UTC.
            v = (v if v.tzinfo else v.replace(tzinfo=timezone.utc)).isoformat()
        out[col.name] = v
    return out
