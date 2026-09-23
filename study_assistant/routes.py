"""路由协调校验、模型与存储；HTTP/SSE 是对浏览器的接口。"""

import asyncio
import json
import logging
from contextlib import aclosing

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from .llm import ModelError
from .prompts import PROMPTS
from .schemas import ApiResponse, ChatRequest, CreateSession, RenameSession
from .storage import now

router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)


def services(request: Request):
    return request.app.state.store, request.app.state.model


def prepare(store, model, session_id: str, payload: ChatRequest):
    if payload.session_id is not None and payload.session_id != session_id:
        raise HTTPException(400, "请求体会话标识与 URL 不一致")
    session = store.writable(session_id)
    model.check_ready()
    messages = [{"role": "system", "content": PROMPTS[session["mode"]]},
                *session["messages"], {"role": "user", "content": payload.message}]
    if sum(len(item["content"]) for item in messages) > 60000:
        raise HTTPException(413, "当前会话过长，请新建会话并粘贴所需上下文")
    return session, messages


@router.get("/sessions")
async def list_sessions(request: Request):
    store, _ = services(request)
    items, warnings = store.list()
    return ApiResponse(data=items, message="；".join(warnings) if warnings else "成功")


@router.post("/sessions")
async def create_session(request: Request, payload: CreateSession | None = None):
    store, _ = services(request)
    payload = payload or CreateSession()
    return ApiResponse(data=store.summary(store.create(payload.mode, payload.name)))


@router.get("/sessions/{session_id}")
async def get_session(session_id: str, request: Request):
    store, _ = services(request)
    return ApiResponse(data=store.read(session_id))


@router.patch("/sessions/{session_id}")
async def rename_session(session_id: str, payload: RenameSession, request: Request):
    store, _ = services(request)
    async with store.edit(session_id):
        session = store.writable(session_id)
        session.update(name=payload.name, custom_name=True, updated_at=now())
        store.save(session)
    return ApiResponse(data=store.summary(session))


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, request: Request):
    store, _ = services(request)
    async with store.edit(session_id):
        path = store.path(session_id)
        if not path.is_file():
            raise HTTPException(404, "会话不存在")
        path.unlink()
    return ApiResponse(message="会话已删除")


@router.post("/sessions/{session_id}/messages")
async def chat(session_id: str, payload: ChatRequest, request: Request):
    store, model = services(request)
    async with store.edit(session_id):
        session, messages = prepare(store, model, session_id, payload)
        async with aclosing(model.stream(messages)) as stream:
            answer = "".join([part async for part in stream])
        if not answer.strip():
            raise ModelError("模型没有返回正文，本轮未保存")
        if await request.is_disconnected():
            raise HTTPException(499, "连接已断开，本轮未保存")
        store.append_turn(session, payload.message, answer)
    return ApiResponse(data=answer)


def event(name: str, data: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/sessions/{session_id}/messages/stream")
async def chat_stream(session_id: str, payload: ChatRequest, request: Request):
    store, model = services(request)
    # 在发送 SSE 响应头之前，优先返回可以确定的 HTTP 错误。
    prepare(store, model, session_id, payload)

    async def generate():
        try:
            async with store.edit(session_id):
                session, messages = prepare(store, model, session_id, payload)
                parts = []
                async with aclosing(model.stream(messages)) as stream:
                    async for part in stream:
                        if await request.is_disconnected():
                            return
                        parts.append(part)
                        yield event("delta", {"content": part})
                answer = "".join(parts)
                if not answer.strip():
                    raise ModelError("模型没有返回正文，本轮未保存")
                if await request.is_disconnected():
                    return
                store.append_turn(session, payload.message, answer)
                yield event("done", {"session": store.summary(session)})
        except asyncio.CancelledError:
            # 浏览器断开时取消上游请求；async with 会释放锁。
            raise
        except (ModelError, HTTPException) as exc:
            message = exc.detail if isinstance(exc, HTTPException) else str(exc)
            yield event("error", {"message": message})
        except Exception as exc:
            logger.error("Stream failed: %s", type(exc).__name__)
            yield event("error", {"message": "服务处理失败，请刷新核对历史后重试"})

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
