import logging
import time

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.config import settings
from app.db.models import Base
from app.db.session import engine
from app.routers import admin, catalog, documents, health, identification, images, search, troubleshooting


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("aibe")


def create_app() -> FastAPI:
    Base.metadata.create_all(bind=engine)
    app = FastAPI(title="AIBE Foundation", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-AIBE-API-Key"],
    )

    @app.middleware("http")
    async def request_logging(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        logger.info("%s %s -> %s %.2fms", request.method, request.url.path, response.status_code, elapsed_ms)
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(_request: Request, exc: RequestValidationError):
        return JSONResponse(status_code=422, content={"ok": False, "error": "validation_error", "detail": exc.errors()})

    @app.exception_handler(SQLAlchemyError)
    async def sqlalchemy_exception_handler(_request: Request, exc: SQLAlchemyError):
        logger.exception("Database error")
        return JSONResponse(status_code=500, content={"ok": False, "error": "database_error", "detail": str(exc)})

    @app.get("/")
    def root():
        return {
            "service": "AIBE Foundation",
            "try": ["/api/health", "/api/ready", "/api/catalog", "/api/identification/cases", "/api/documents/qa"],
        }

    app.include_router(health.router, prefix="/api", tags=["health"])
    app.include_router(catalog.router, prefix="/api", tags=["catalog"])
    app.include_router(search.router, prefix="/api", tags=["search"])
    app.include_router(images.router, prefix="/api", tags=["images"])
    app.include_router(identification.router, prefix="/api", tags=["identification"])
    app.include_router(documents.router, prefix="/api", tags=["documents"])
    app.include_router(troubleshooting.router, prefix="/api", tags=["troubleshooting"])
    app.include_router(admin.router, prefix="/api", tags=["admin"])
    return app


app = create_app()
