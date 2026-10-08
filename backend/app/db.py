from contextlib import contextmanager

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


_sqlite = settings.database_url.startswith("sqlite")
if _sqlite:
    settings.data_dir.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False, "timeout": 30} if _sqlite else {},
)

if _sqlite:

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(conn, _):
        cur = conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()


SessionLocal = sessionmaker(engine, expire_on_commit=False)


@contextmanager
def session():
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def init_db() -> None:
    from . import models  # noqa: F401  register tables

    Base.metadata.create_all(engine)
    _add_missing_columns()
    _relativize_document_paths()


def _relativize_document_paths() -> None:
    """Older data dirs stored absolute file paths; store them relative to data_dir so the folder can move."""
    from .models import Document

    with session() as s:
        for d in s.query(Document):
            d.path = settings.stored_path(settings.resolve(d.path))
            if d.pdf_path:
                d.pdf_path = settings.stored_path(settings.resolve(d.pdf_path))


def _add_missing_columns() -> None:
    """create_all never alters tables; add new nullable columns so existing data dirs keep working."""
    insp = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            existing = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name not in existing:
                    conn.execute(text(f"ALTER TABLE {table.name} ADD COLUMN {col.name} {col.type.compile(engine.dialect)}"))
