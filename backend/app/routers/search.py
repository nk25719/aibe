from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.config import settings
from app.db.session import get_db
from app.schemas.api import SearchResponse
from app.services.catalog_query import CatalogSearchParams, search_catalog

router = APIRouter()


@router.get("/search", response_model=SearchResponse)
def api_search(
    q: str = Query("", description="query", max_length=200),
    manufacturer: str | None = Query(default=None, max_length=255),
    equipment_family: str | None = Query(default=None, max_length=255),
    equipment_model: str | None = Query(default=None, max_length=255),
    include_inactive: bool = Query(default=False),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    return search_catalog(
        db,
        CatalogSearchParams(
            q=q,
            manufacturer=manufacturer,
            equipment_family=equipment_family,
            equipment_model=equipment_model,
            include_inactive=include_inactive,
            limit=limit,
            offset=offset,
            enable_legacy_fallback=settings.enable_legacy_search_fallback,
        ),
    )
