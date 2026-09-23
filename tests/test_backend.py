import asyncio
import json
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from study_assistant.application import create_app
from study_assistant.config import Settings
from study_assistant.llm import ModelError, ModelService
from study_assistant.storage import SessionStore


class FakeModel:
    def __init__(self):
        self.calls = []
        self.failure = False

    def check_ready(self):
        pass

    async def stream(self, messages):
        self.calls.append(messages)
        yield "你好，"
        if self.failure:
            raise ModelError("模拟连接中断")
        yield "这里是完整回复。"

    async def close(self):
        pass


@pytest.fixture
def environment(tmp_path):
    model = FakeModel()
    app = create_app(Settings(sessions_dir=tmp_path), model=model)
    with TestClient(app) as client:
        yield client, model, app.state.store


def new_session(client, **payload):
    response = client.post("/api/sessions", json=payload)
    assert response.status_code == 200
    return response.json()["data"]["id"]


def test_crud_and_custom_title(environment):
    client, model, store = environment
    first = new_session(client, mode="code")
    second = new_session(client, mode="paper", name="精读摘要")
    assert first != second
    assert client.get(f"/api/sessions/{first}").json()["data"]["messages"] == []
    assert client.post(f"/api/sessions/{first}/messages", json={"message": "解释函数"}).status_code == 200
    saved = store.read(first)
    assert saved["name"] == "解释函数"
    assert [m["role"] for m in saved["messages"]] == ["user", "assistant"]
    assert client.patch(f"/api/sessions/{second}", json={"name": "我的论文"}).status_code == 200
    client.post(f"/api/sessions/{second}/messages", json={"message": "摘要内容"})
    assert store.read(second)["name"] == "我的论文"
    assert client.get("/api/sessions").json()["data"][0]["id"] == second
    assert client.delete(f"/api/sessions/{first}").status_code == 200
    assert client.get(f"/api/sessions/{first}").status_code == 404
    assert client.delete(f"/api/sessions/{first}").status_code == 404


@pytest.mark.parametrize("mode,keyword", [("code", "代码导师"), ("paper", "原文依据"), ("review", "一次只出一道题")])
def test_modes_and_sse(environment, mode, keyword):
    client, model, store = environment
    session_id = new_session(client, mode=mode)
    response = client.post(f"/api/sessions/{session_id}/messages/stream", json={"message": "学习材料"})
    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    assert response.text.count("event: delta") == 2
    assert "event: done" in response.text
    assert keyword in model.calls[0][0]["content"]
    assert len(store.read(session_id)["messages"]) == 2


def test_legacy_is_readonly_and_corruption_isolated(environment):
    client, model, store = environment
    legacy = "2026-09-23_12-22-49"
    path = store.directory / f"{legacy}.json"
    original = json.dumps({"current_session": legacy, "messages": [{"role": "assistant", "content": "你好"}]}).encode()
    path.write_bytes(original)
    broken = store.directory / f"{uuid4()}.json"
    broken.write_text("{ broken", encoding="utf-8")
    listing = client.get("/api/sessions").json()
    assert len(listing["data"]) == 1
    assert "无法读取" in listing["message"]
    assert listing["data"][0]["read_only"] is True
    assert client.patch(f"/api/sessions/{legacy}", json={"name": "rename"}).status_code == 409
    assert client.post(f"/api/sessions/{legacy}/messages", json={"message": "hi"}).status_code == 409
    assert path.read_bytes() == original
    assert broken.read_text(encoding="utf-8") == "{ broken"
    assert client.get(f"/api/sessions/{broken.stem}").status_code == 422
    assert client.delete(f"/api/sessions/{legacy}").status_code == 200


def test_invalid_input_and_path(environment):
    client, model, store = environment
    session_id = new_session(client)
    for message in ("", "   ", "a" * 24001):
        assert client.post(f"/api/sessions/{session_id}/messages", json={"message": message}).status_code == 422
    assert client.post("/api/sessions", json={"mode": "other"}).status_code == 422
    assert client.patch(f"/api/sessions/{session_id}", json={"name": "ok", "mode": "paper"}).status_code == 422
    assert client.get("/api/sessions/invalid").status_code == 400
    assert client.get(f"/api/sessions/{uuid4()}").status_code == 404
    assert client.post(f"/api/sessions/{session_id}/messages", json={"message": "hi", "session_id": "different"}).status_code == 400
    assert client.post(f"/api/sessions/{session_id}/messages", json={"message": "hi", "session_id": session_id}).status_code == 200
    for invalid in ("../outside", "..\\outside", "C:\\outside", session_id + "/.."):
        with pytest.raises(Exception) as exc:
            store.path(invalid)
        assert exc.value.status_code == 400


def test_missing_key_still_serves_home(tmp_path):
    app = create_app(Settings(api_key="", sessions_dir=tmp_path))
    with TestClient(app) as client:
        assert client.get("/").status_code == 200
        session_id = new_session(client)
        for endpoint in ("messages", "messages/stream"):
            response = client.post(f"/api/sessions/{session_id}/{endpoint}", json={"message": "hello"})
            assert response.status_code == 503
            assert "密钥" in response.json()["message"]
        assert app.state.store.read(session_id)["messages"] == []


def test_failure_never_saves_partial_turn_and_can_retry(environment):
    client, model, store = environment
    session_id = new_session(client)
    model.failure = True
    response = client.post(f"/api/sessions/{session_id}/messages/stream", json={"message": "hello"})
    assert "event: delta" in response.text and "event: error" in response.text
    assert "event: done" not in response.text
    assert store.read(session_id)["messages"] == []
    assert client.post(f"/api/sessions/{session_id}/messages", json={"message": "hello"}).status_code == 502
    model.failure = False
    assert client.post(f"/api/sessions/{session_id}/messages", json={"message": "retry"}).status_code == 200
    assert len(store.read(session_id)["messages"]) == 2


def test_atomic_write_failure_preserves_existing(environment, monkeypatch):
    client, model, store = environment
    session_id = new_session(client)
    original = store.path(session_id).read_bytes()
    def fail(*args):
        raise OSError("simulated disk failure")
    monkeypatch.setattr("study_assistant.storage.os.replace", fail)
    with pytest.raises(OSError):
        store.append_turn(store.read(session_id), "hello", "answer")
    assert store.path(session_id).read_bytes() == original
    assert not list(store.directory.glob("*.tmp"))


def test_busy_session_rejects_mutations_and_releases_lock(tmp_path):
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        class SlowModel(FakeModel):
            async def stream(self, messages):
                entered.set()
                await release.wait()
                yield "answer"
        app = create_app(Settings(sessions_dir=tmp_path), model=SlowModel())
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
            session_id = (await client.post("/api/sessions", json={})).json()["data"]["id"]
            endpoint = f"/api/sessions/{session_id}"
            task = asyncio.create_task(client.post(endpoint + "/messages", json={"message": "one"}))
            await entered.wait()
            assert (await client.post(endpoint + "/messages", json={"message": "two"})).status_code == 409
            assert (await client.patch(endpoint, json={"name": "busy"})).status_code == 409
            assert (await client.delete(endpoint)).status_code == 409
            release.set()
            assert (await task).status_code == 200
            assert (await client.delete(endpoint)).status_code == 200
    asyncio.run(scenario())


def test_model_only_returns_body_and_requires_stop():
    async def scenario():
        async def run(finish):
            chunks = [
                {"choices": [{"index": 0, "delta": {"reasoning_content": "private"}, "finish_reason": None}]},
                {"choices": [{"index": 0, "delta": {"content": "正文"}, "finish_reason": None}]},
                {"choices": [{"index": 0, "delta": {}, "finish_reason": finish}]},
            ]
            body = "".join("data: " + json.dumps(item) + "\n\n" for item in chunks) + "data: [DONE]\n\n"
            def handler(request):
                return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})
            from openai import AsyncOpenAI
            model = ModelService(Settings(api_key="test-only"))
            model._client = AsyncOpenAI(api_key="test-only", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
            try:
                return "".join([part async for part in model.stream([{"role": "user", "content": "hi"}])])
            finally:
                await model.close()
        assert await run("stop") == "正文"
        with pytest.raises(ModelError):
            await run("length")
        with pytest.raises(ModelError):
            await run(None)
    asyncio.run(scenario())


def test_disconnect_cancels_upstream_and_does_not_persist(tmp_path):
    async def scenario():
        disconnected, closed = asyncio.Event(), asyncio.Event()
        class DisconnectModel(FakeModel):
            async def stream(self, messages):
                try:
                    yield "partial"
                    await asyncio.Event().wait()
                finally:
                    closed.set()
        app = create_app(Settings(sessions_dir=tmp_path), model=DisconnectModel())
        session = app.state.store.create("code", None)
        request_body = json.dumps({"message": "hello"}).encode()
        first = True
        async def receive():
            nonlocal first
            if first:
                first = False
                return {"type": "http.request", "body": request_body, "more_body": False}
            await disconnected.wait()
            return {"type": "http.disconnect"}
        async def send(message):
            if message["type"] == "http.response.body" and b"event: delta" in message.get("body", b""):
                disconnected.set()
        scope = {
            "type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
            "method": "POST", "scheme": "http", "path": f"/api/sessions/{session['id']}/messages/stream",
            "query_string": b"", "headers": [(b"content-type", b"application/json")],
            "client": ("127.0.0.1", 1), "server": ("test", 80), "http_version": "1.1",
        }
        await asyncio.wait_for(app(scope, receive, send), timeout=3)
        assert closed.is_set()
        assert app.state.store.read(session["id"])["messages"] == []
        async with app.state.store.edit(session["id"]):
            pass
    asyncio.run(scenario())


def test_context_limit_does_not_silently_truncate(environment):
    client, model, store = environment
    session_id = new_session(client)
    session = store.read(session_id)
    session["messages"] = [{"role": "assistant", "content": "x" * 60000}]
    store.save(session)
    response = client.post(f"/api/sessions/{session_id}/messages", json={"message": "hello"})
    assert response.status_code == 413
    assert not model.calls
