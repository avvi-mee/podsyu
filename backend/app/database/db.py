from contextlib import contextmanager
from datetime import datetime, timezone

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import DB_PATH

engine = create_engine(
    f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False, "timeout": 30}
)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(conn, _):
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


SessionLocal = sessionmaker(engine, expire_on_commit=False)


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    def to_dict(self) -> dict:
        out = {}
        for c in self.__table__.columns:
            v = getattr(self, c.name)
            # Datetimes are stored as naive UTC; mark them as UTC for the frontend.
            out[c.name] = v.isoformat() + "Z" if isinstance(v, datetime) else v
        return out


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


def get_db():
    """FastAPI dependency."""
    with session() as s:
        yield s


def init_db():
    from app.models import models  # noqa: F401  (register tables)

    Base.metadata.create_all(engine)
    # Tiny migration: add columns introduced after the database was created (all new columns are nullable).
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            have = {row[1] for row in conn.exec_driver_sql(f'PRAGMA table_info("{table.name}")')}
            for col in table.columns:
                if col.name not in have:
                    conn.exec_driver_sql(f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {col.type.compile(engine.dialect)}')
