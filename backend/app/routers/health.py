from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.db.session import get_db
from app.schemas.api import HealthResponse
from app.services.image_index import image_index

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health():
    return {
        "ok": True,
        "service": settings.app_name,
        "database_url": settings.database_url.split("@")[-1],
        "legacy_parts_db": str(settings.legacy_parts_db_path),
        "image_index": image_index.status(),
    }


@router.get("/ready")
def ready(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(503, f"Database not ready: {exc}")
    return {"ok": True, "database": "ready", "image_index": image_index.status()}
