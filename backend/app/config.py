import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]


class Settings:
    app_name: str = "AIBE"
    api_key: str | None
    cors_origins: list[str]
    database_url: str
    legacy_parts_db_path: Path
    embed_dir: Path
    max_upload_bytes: int

    def __init__(self) -> None:
        self.api_key = os.getenv("AIBE_API_KEY")
        self.cors_origins = [
            origin.strip()
            for origin in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
            if origin.strip()
        ]
        self.database_url = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'aibe_foundation.db'}")
        self.legacy_parts_db_path = Path(os.getenv("PARTS_DB_PATH", str(BASE_DIR / "parts.db"))).resolve()
        self.embed_dir = Path(os.getenv("EMBED_DIR", str(BASE_DIR / "embeddings"))).resolve()
        self.max_upload_bytes = int(os.getenv("MAX_UPLOAD_BYTES", str(8 * 1024 * 1024)))


settings = Settings()
