"""
Database engine + session management.

Defaults to a local SQLite file so the whole project runs with zero external
setup. Point DATABASE_URL at PostgreSQL / Supabase for production, e.g.:

    postgresql+psycopg2://user:password@host:5432/trustguard
"""
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker

logger = logging.getLogger("trustguard.db")
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'trustguard.db'}")

if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}
elif DATABASE_URL.startswith("postgres"):
    # Timestamps are stored as naive UTC ("timestamp without time zone") and written as aware datetimes.
    # Without this the server's session TimeZone would shift every stored time on a non-UTC database.
    connect_args = {"options": "-c timezone=utc"}
else:
    connect_args = {}

engine = create_engine(DATABASE_URL, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)

Base = declarative_base()


def get_db():
    """FastAPI dependency that yields a scoped DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables. Called once at startup."""
    import database.models  # noqa: F401  (ensure models are registered)

    Base.metadata.create_all(bind=engine)
    _ensure_columns()
    _ensure_indexes()


# Columns added after the first release. create_all() never alters existing tables,
# so older trustguard.db files are upgraded in place here (additive only).
_ADDED_COLUMNS = {
    "sensors": {"data_source": "'simulation'", "last_seen_at": None, "registered_at": None, "name": None, "hardware_model": None},
    "sensor_readings": {"source": "'simulation'", "is_delayed": "FALSE"},
}


def _ensure_columns():
    insp = inspect(engine)
    for table_name, cols in _ADDED_COLUMNS.items():
        table = Base.metadata.tables[table_name]
        existing = {c["name"] for c in insp.get_columns(table_name)}
        for name, default in cols.items():
            if name in existing:
                continue
            ddl = f"ALTER TABLE {table_name} ADD COLUMN {name} {table.c[name].type.compile(dialect=engine.dialect)}"
            if default:
                ddl += f" DEFAULT {default}"
            with engine.begin() as conn:
                conn.execute(text(ddl))


def _ensure_indexes():
    """
    create_all() only creates indexes together with a brand-new table, so databases from earlier builds get the
    reading indexes here. Existing data is never modified: if the unique hardware-reading index cannot be built
    because duplicate readings already exist, the app keeps running (it still rejects duplicates itself) and the log
    says how to clean them up.
    """
    for index in Base.metadata.tables["sensor_readings"].indexes:
        try:
            index.create(bind=engine, checkfirst=True)
        except Exception as exc:  # noqa: BLE001 - IntegrityError / OperationalError differ per database
            if index.unique:
                logger.warning(
                    "Could not create unique index %s (%s). Duplicate hardware readings probably exist; "
                    "run `python dedupe_hardware_readings.py` (dry run) to see and remove them, then restart.",
                    index.name, str(exc).splitlines()[0])
            else:
                logger.warning("Could not create index %s: %s", index.name, exc)
