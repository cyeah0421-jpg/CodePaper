"""Pydantic 是接口入口的检查员，不是数据库。"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Mode = Literal["code", "paper", "review"]


class ApiResponse(BaseModel):
    code: int = 200
    message: str = "成功"
    data: Any = None


class InputModel(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class CreateSession(InputModel):
    mode: Mode = "code"
    name: str | None = Field(default=None, min_length=1, max_length=60)


class RenameSession(InputModel):
    name: str = Field(min_length=1, max_length=60)


class ChatRequest(InputModel):
    message: str = Field(min_length=1, max_length=24000)
    # 只用于兼容旧客户端，真正的目标始终取自 URL 路径。
    session_id: str | None = None
