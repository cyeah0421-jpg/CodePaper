"""应用工厂让正式服务和测试使用同一套组装方式。"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException

from .config import Settings
from .llm import ModelError, ModelService
from .routes import router
from .storage import SessionStore

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, model=None) -> FastAPI:
    settings = settings or Settings.from_env()
    model_service = model if model is not None else ModelService(settings)

    @asynccontextmanager
    async def lifespan(app):
        try:
            yield
        finally:
            await model_service.close()

    app = FastAPI(title="知行助手", lifespan=lifespan)
    app.state.store = SessionStore(settings.sessions_dir)
    app.state.model = model_service
    app.include_router(router)
    app.mount("/static", StaticFiles(directory=settings.static_dir), name="static")

    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(settings.static_dir / "index.html")

    def error(code: int, message: str):
        return JSONResponse(status_code=code, content={"code": code, "message": message, "data": None})

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return error(exc.status_code, str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return error(422, "输入不符合要求：消息须为 1–24000 字符，名称须为 1–60 字符，模式为 code/paper/review")

    @app.exception_handler(ModelError)
    async def model_error(request: Request, exc: ModelError):
        return error(exc.status_code, str(exc))

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        logger.error("Request failed: %s", type(exc).__name__)
        return error(500, "服务处理失败，请稍后重试")

    return app
