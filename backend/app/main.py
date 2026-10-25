import logging
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from ml_scoring.local_inference import LocalInferenceService
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm.exc import StaleDataError

from app.ai.router import router as chat_router
from app.applications.router import bank_router, client_router, compat_router, draft_router
from app.auth.models import User
from app.auth.router import admin_router
from app.auth.router import router as auth_router
from app.catalog import router as catalog_router
from app.config import get_settings
from app.database import make_engine
from app.feed.router import router as feed_router
from app.loans.router import router as loan_router
from app.notifications.router import router as notification_router
from app.products.router import router as product_router
from app.profiles.router import router as profile_router
from app.risk.router import router as risk_router
from app.scoring.errors import problem_response
from app.scoring.router import router as scoring_router


def create_app(settings=None, engine=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.settings = settings or get_settings()
        app.state.engine = engine or make_engine(app.state.settings.database_url)
        app.state.scoring_service = None
        try:
            app.state.scoring_service = LocalInferenceService.from_artifact_directory(
                app.state.settings.scoring_models_dir
            )
        except Exception as exc:
            # Логируем только тип: ошибка загрузчика может содержать локальные пути.
            logging.getLogger(__name__).warning(
                "Scoring runtime unavailable: %s", type(exc).__name__
            )
        yield
        if engine is None:
            app.state.engine.dispose()

    app = FastAPI(
        title="Умный кредитный кабинет предпринимателя",
        version="0.1.0",
        description="Демонстрационный кредитный конвейер. Без реальных проверок и выдачи средств.",
        lifespan=lifespan,
    )
    for router in (
        chat_router,
        auth_router,
        admin_router,
        profile_router,
        product_router,
        catalog_router,
        client_router,
        draft_router,
        bank_router,
        compat_router,
        loan_router,
        feed_router,
        notification_router,
        risk_router,
        scoring_router,
    ):
        app.include_router(router, prefix="/api/v1")

    @app.middleware("http")
    async def privacy_headers(request, call_next):
        request.state.request_id = uuid4()
        if request.url.path.startswith("/api/v1/scoring/"):
            try:
                request.state.request_id = UUID(
                    request.headers.get("X-Request-ID", str(request.state.request_id))
                )
            except ValueError:
                return problem_response(request, 422, "SCORING_INVALID_INPUT")
        response = await call_next(request)
        if "Cache-Control" not in response.headers:
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Request-ID"] = str(request.state.request_id)
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        if request.url.path.startswith("/api/v1/scoring/"):
            detail = exc.detail if isinstance(exc.detail, dict) else {}
            return problem_response(
                request,
                exc.status_code,
                detail.get("code", "SCORING_ERROR"),
                detail.get("errors", []),
            )
        return JSONResponse(
            status_code=exc.status_code, content={"detail": exc.detail}, headers=exc.headers
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        errors = [
            {"field": ".".join(map(str, item["loc"])), "code": item["type"], "message": item["msg"]}
            for item in exc.errors()
        ]
        if request.url.path.startswith("/api/v1/scoring/"):
            return problem_response(request, 422, "SCORING_INVALID_INPUT", errors)
        return JSONResponse(
            status_code=422, content={"detail": {"code": "INVALID_INPUT", "errors": errors}}
        )

    @app.exception_handler(IntegrityError)
    async def integrity_error(request, exc):
        if request.url.path.startswith("/api/v1/scoring/"):
            return problem_response(request, 409, "DATA_CONFLICT")
        return JSONResponse(status_code=409, content={"detail": {"code": "DATA_CONFLICT"}})

    @app.exception_handler(StaleDataError)
    async def stale_error(request, exc):
        if request.url.path.startswith("/api/v1/scoring/"):
            return problem_response(request, 409, "APPLICATION_VERSION_CONFLICT")
        return JSONResponse(
            status_code=409, content={"detail": {"code": "APPLICATION_VERSION_CONFLICT"}}
        )

    @app.exception_handler(OperationalError)
    async def database_error(request, exc):
        if request.url.path.startswith("/api/v1/scoring/"):
            return problem_response(request, 503, "DATABASE_UNAVAILABLE")
        return JSONResponse(status_code=503, content={"detail": {"code": "DATABASE_UNAVAILABLE"}})

    @app.get("/health/scoring")
    def scoring_health(request: Request):
        if request.app.state.scoring_service is None:
            return JSONResponse(status_code=503, content={"status": "unavailable"})
        service = request.app.state.scoring_service
        return {"status": "ok", "bundle_sha256": service.bundle_sha256}

    @app.get("/health")
    def health(request: Request):
        with request.app.state.engine.connect() as connection:
            connection.execute(select(User.id).limit(0))
        return {"status": "ok", "demonstration_only": True}

    return app


app = create_app()
