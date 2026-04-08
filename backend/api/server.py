import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logger = logging.getLogger("niftymind.api")

_app_state = {}


def get_app_state():
    return _app_state


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("FastAPI server starting")
    yield
    logger.info("FastAPI server shutting down")


def create_app(
    executor=None,
    position_tracker=None,
    redis_publisher=None,
    config=None,
) -> FastAPI:
    app = FastAPI(
        title="NiftyMind API",
        version="1.0.0",
        description="Multi-agent AI options trading system for NSE Nifty 50 & BankNifty",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    _app_state["executor"] = executor
    _app_state["position_tracker"] = position_tracker
    _app_state["publisher"] = redis_publisher
    _app_state["redis_publisher"] = redis_publisher
    _app_state["config"] = config
    _app_state["news_cache"] = []  # In-memory news cache (fallback when DB unavailable)

    from api.routes import router
    app.include_router(router, prefix="/api")

    from api.websocket_handler import ws_router
    app.include_router(ws_router)

    return app
