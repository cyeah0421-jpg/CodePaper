"""JSON 仓库：校验路径、兼容历史、原子保存、单进程会话锁。"""

import asyncio
import json
import logging
import os
import re
import tempfile
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException

from .prompts import MODE_NAMES

logger = logging.getLogger(__name__)
SESSION_ID = re.compile(r"(?:[0-9a-f]{32}|[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}|\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})\Z")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SessionStore:
    def __init__(self, directory: Path):
        self.directory = directory.resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self._locks: dict[str, asyncio.Lock] = {}

    def path(self, session_id: str) -> Path:
        if not SESSION_ID.fullmatch(session_id):
            raise HTTPException(400, "会话标识格式不正确")
        path = self.directory / f"{session_id}.json"
        if path.is_symlink() or path.resolve().parent != self.directory:
            raise HTTPException(400, "无效的会话路径")
        return path

    @asynccontextmanager
    async def edit(self, session_id: str):
        self.path(session_id)
        lock = self._locks.setdefault(session_id, asyncio.Lock())
        # 所有入口均运行在同一个事件循环；忙时明确拒绝，不排队重复生成。
        if lock.locked():
            raise HTTPException(409, "该会话正在生成回复，请稍后操作")
        async with lock:
            yield

    def read(self, session_id: str) -> dict:
        path = self.path(session_id)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or not isinstance(raw.get("messages"), list):
                raise ValueError("invalid session")
            messages = raw["messages"]
            if any(not isinstance(m, dict) or m.get("role") not in ("user", "assistant")
                   or not isinstance(m.get("content"), str) for m in messages):
                raise ValueError("invalid messages")
            if "version" not in raw:
                stamp = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
                return dict(id=session_id, name="历史字谜会话", mode="legacy", read_only=True,
                            created_at=stamp, updated_at=stamp, messages=messages)
            if (raw.get("version") != 1 or raw.get("id") != session_id
                    or raw.get("mode") not in MODE_NAMES
                    or not isinstance(raw.get("name"), str)
                    or not isinstance(raw.get("custom_name"), bool)):
                raise ValueError("invalid metadata")
            for key in ("created_at", "updated_at"):
                if not isinstance(raw.get(key), str):
                    raise ValueError("invalid timestamp")
                datetime.fromisoformat(raw[key])
            return {**raw, "read_only": False}
        except FileNotFoundError:
            raise HTTPException(404, "会话不存在") from None
        except (ValueError, TypeError, UnicodeError, KeyError):
            raise HTTPException(422, "会话文件格式损坏，未修改原文件") from None

    @staticmethod
    def summary(session: dict) -> dict:
        return {key: session[key] for key in
                ("id", "name", "mode", "created_at", "updated_at", "read_only")}

    def list(self) -> tuple[list[dict], list[str]]:
        items, warnings = [], []
        for path in self.directory.glob("*.json"):
            try:
                items.append(self.summary(self.read(path.stem)))
            except (HTTPException, OSError):
                warnings.append(f"无法读取会话文件：{path.name}（原文件已保留）")
                logger.warning("Skipped unreadable session file: %s", path.name)
        items.sort(key=lambda item: item["updated_at"], reverse=True)
        return items, warnings

    def save(self, session: dict) -> None:
        path = self.path(session["id"])
        payload = {key: value for key, value in session.items() if key != "read_only"}
        # 同目录临时文件使 os.replace 可以进行原子替换。
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".tmp",
                                             dir=self.directory, delete=False) as handle:
                temporary = Path(handle.name)
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()

    def create(self, mode: str, name: str | None) -> dict:
        stamp = now()
        session = dict(version=1, id=str(uuid4()), mode=mode, name=name or f"新{MODE_NAMES[mode]}会话",
                       custom_name=bool(name), created_at=stamp, updated_at=stamp,
                       messages=[], read_only=False)
        self.save(session)
        return session

    def writable(self, session_id: str) -> dict:
        session = self.read(session_id)
        if session["read_only"]:
            raise HTTPException(409, "历史字谜会话只读，请新建学习会话")
        return session

    def append_turn(self, session: dict, message: str, answer: str) -> None:
        if not session["messages"] and not session["custom_name"]:
            session["name"] = " ".join(message.split())[:28]
        session["messages"].extend([
            {"role": "user", "content": message},
            {"role": "assistant", "content": answer},
        ])
        session["updated_at"] = now()
        self.save(session)
