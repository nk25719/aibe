from fastapi import APIRouter

from app.schemas.api import CatalogResponse
from app.services.catalog import get_catalog_options

router = APIRouter()


@router.get("/catalog", response_model=CatalogResponse)
def catalog():
    return {"ok": True, **get_catalog_options()}
