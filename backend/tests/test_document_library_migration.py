import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import sessionmaker

from app.db.models import Document, DocumentVersion


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"


def _alembic_config(database_url: str) -> Config:
    config = Config(str(BACKEND / "alembic.ini"))
    config.attributes["database_url"] = database_url
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def _seed_0005_database(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        conn.execute("INSERT INTO alembic_version (version_num) VALUES ('0005_normalized_catalog_authority')")
        conn.execute(
            """
            CREATE TABLE documents (
                id INTEGER PRIMARY KEY,
                title VARCHAR(500) NOT NULL,
                document_type VARCHAR(100),
                document_number VARCHAR(255),
                manufacturer_id INTEGER,
                manufacturer_text VARCHAR(255),
                equipment_family_text VARCHAR(255),
                equipment_model_text VARCHAR(255),
                language VARCHAR(50),
                access_classification VARCHAR(100),
                source_url VARCHAR(1000),
                internal_reference VARCHAR(500),
                ingestion_status VARCHAR(100),
                ingestion_errors JSON,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                is_active BOOLEAN NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE document_versions (
                id INTEGER PRIMARY KEY,
                document_id INTEGER NOT NULL,
                revision VARCHAR(100) NOT NULL,
                published_at DATE,
                effective_at DATE,
                file_sha1 VARCHAR(64),
                source_path VARCHAR(1000),
                duplicate_of_version_id INTEGER,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                is_active BOOLEAN NOT NULL,
                UNIQUE(document_id, revision)
            )
            """
        )
        conn.execute(
            """
            INSERT INTO documents (
                id, title, document_type, document_number, manufacturer_text,
                equipment_model_text, language, access_classification,
                ingestion_status, created_at, updated_at, is_active
            ) VALUES (
                1, 'Legacy Doc', 'service_manual', 'LEG-1', 'GE Healthcare',
                'TM-100', 'en', 'fixture', 'completed',
                '2026-08-23 00:00:00', '2026-08-23 00:00:00', 1
            )
            """
        )
        conn.execute(
            """
            INSERT INTO document_versions (
                id, document_id, revision, effective_at, file_sha1, source_path,
                created_at, updated_at, is_active
            ) VALUES (
                1, 1, 'A', '2026-01-01',
                'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
                'fixture.pdf', '2026-08-23 00:00:00', '2026-08-23 00:00:00', 1
            )
            """
        )


def test_existing_0005_document_database_migrates_and_preserves_rows(tmp_path):
    db_path = tmp_path / "existing-0005.db"
    _seed_0005_database(db_path)
    database_url = f"sqlite:///{db_path}"

    command.upgrade(_alembic_config(database_url), "head")

    engine = create_engine(database_url, future=True)
    inspector = inspect(engine)
    document_columns = {column["name"] for column in inspector.get_columns("documents")}
    version_columns = {column["name"] for column in inspector.get_columns("document_versions")}
    assert {"equipment_family_id", "equipment_model_id", "verification_status", "notes"} <= document_columns
    assert {
        "expires_at",
        "lifecycle_status",
        "superseded_by_version_id",
        "original_filename",
        "mime_type",
        "file_size",
        "uploaded_at",
        "uploaded_by",
        "file_sha256",
    } <= version_columns
    Session = sessionmaker(bind=engine, future=True)
    with Session() as session:
        doc = session.scalar(select(Document).where(Document.document_number == "LEG-1"))
        version = session.scalar(select(DocumentVersion).where(DocumentVersion.document_id == doc.id))
        assert doc.title == "Legacy Doc"
        assert doc.verification_status == "unverified"
        assert version.expires_at is None
        assert version.lifecycle_status == "draft"
        assert version.file_sha256 == "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

    command.downgrade(_alembic_config(database_url), "0005_normalized_catalog_authority")
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1
        assert conn.execute("SELECT file_sha1 FROM document_versions").fetchone()[0] == "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        downgraded_columns = {row[1] for row in conn.execute("PRAGMA table_info(document_versions)").fetchall()}
        assert "file_sha256" not in downgraded_columns


def test_clean_database_upgrades_through_full_chain(tmp_path):
    db_path = tmp_path / "clean.db"
    database_url = f"sqlite:///{db_path}"

    command.upgrade(_alembic_config(database_url), "head")

    engine = create_engine(database_url, future=True)
    inspector = inspect(engine)
    assert "documents" in inspector.get_table_names()
    assert "expires_at" in {column["name"] for column in inspector.get_columns("document_versions")}
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one() == "0006_technical_document_library"


def test_document_evaluation_is_isolated_and_repeatable(tmp_path):
    env = os.environ.copy()
    env["DOCUMENT_UPLOAD_DIR"] = str(tmp_path / "uploads")
    first = subprocess.run(
        [sys.executable, str(BACKEND / "evaluate_documents.py")],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    second = subprocess.run(
        [sys.executable, str(BACKEND / "evaluate_documents.py")],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    assert '"database_is_temporary": true' in first.stdout
    assert '"database_is_temporary": true' in second.stdout
    assert '"retrieval_hit_rate": 1.0' in second.stdout
