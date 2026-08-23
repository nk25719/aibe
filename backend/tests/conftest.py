import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("PARTS_DB_PATH", str(BACKEND / "parts.db"))
os.environ.setdefault("EMBED_DIR", str(BACKEND / "missing-test-embeddings"))

from app.db.models import Base  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402
from app.services.import_parts import import_parts_spreadsheet  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def normalized_app_catalog():
    Base.metadata.create_all(engine)
    with SessionLocal() as session:
        import_parts_spreadsheet(session)


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    with Session() as session:
        yield session
