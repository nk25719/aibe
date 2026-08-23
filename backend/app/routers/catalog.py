from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.api import CatalogResponse
from app.services.catalog import get_catalog_options

router = APIRouter()


@router.get("/catalog", response_model=CatalogResponse)
def catalog(include_inactive: bool = Query(default=False), db: Session = Depends(get_db)):
    return {"ok": True, **get_catalog_options(db, include_inactive=include_inactive)}
