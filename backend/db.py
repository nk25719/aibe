from app.config import settings
from app.services.legacy_search import search_parts

DB_PATH = settings.legacy_parts_db_path

__all__ = ["DB_PATH", "search_parts"]
