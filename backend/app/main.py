from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
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


def create_app(settings=None, engine=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.settings = settings or get_settings()
        app.state.engine = engine or make_engine(app.state.settings.database_url)
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
    ):
        app.include_router(router, prefix="/api/v1")

    @app.middleware("http")
    async def privacy_headers(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        errors = [
            {"field": ".".join(map(str, item["loc"])), "code": item["type"], "message": item["msg"]}
            for item in exc.errors()
        ]
        return JSONResponse(
            status_code=422, content={"detail": {"code": "INVALID_INPUT", "errors": errors}}
        )

    @app.exception_handler(IntegrityError)
    async def integrity_error(request, exc):
        return JSONResponse(status_code=409, content={"detail": {"code": "DATA_CONFLICT"}})

    @app.exception_handler(StaleDataError)
    async def stale_error(request, exc):
        return JSONResponse(
            status_code=409, content={"detail": {"code": "APPLICATION_VERSION_CONFLICT"}}
        )

    @app.exception_handler(OperationalError)
    async def database_error(request, exc):
        return JSONResponse(status_code=503, content={"detail": {"code": "DATABASE_UNAVAILABLE"}})

    @app.get("/health")
    def health(request: Request):
        with request.app.state.engine.connect() as connection:
            connection.execute(select(User.id).limit(0))
        return {"status": "ok", "demonstration_only": True}

    return app


app = create_app()
