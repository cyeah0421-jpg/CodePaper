"""只负责与模型通信；正文增量向上交给路由，不保存会话。"""

import logging
from collections.abc import AsyncIterator

from openai import AsyncOpenAI, OpenAIError, APITimeoutError

from .config import Settings

logger = logging.getLogger(__name__)


class ModelError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


class ModelService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._client: AsyncOpenAI | None = None

    def check_ready(self) -> None:
        if not self.settings.api_key:
            raise ModelError("尚未配置模型密钥，请在 .env 中设置 DEEPSEEK_API_KEY 或 LLM_API_KEY 后重启", 503)
        if not self.settings.model:
            raise ModelError("尚未配置 LLM_MODEL，请设置后重启", 503)

    async def stream(self, messages: list[dict]) -> AsyncIterator[str]:
        self.check_ready()
        if self._client is None:
            self._client = AsyncOpenAI(api_key=self.settings.api_key, base_url=self.settings.base_url,
                                       timeout=self.settings.timeout, max_retries=0)
        try:
            response = await self._client.chat.completions.create(
                model=self.settings.model, messages=messages, stream=True,
            )
            finished, has_text = False, False
            async with response:
                async for chunk in response:
                    if not chunk.choices:
                        continue
                    choice = chunk.choices[0]
                    # reasoning_content 不参与输出和存储。
                    if choice.delta.content:
                        has_text = True
                        yield choice.delta.content
                    if choice.finish_reason is not None:
                        if choice.finish_reason != "stop":
                            raise ModelError("模型未完整回答（可能达到长度限制），本轮未保存，请缩短问题后重试")
                        finished = True
            if not finished or not has_text:
                raise ModelError("模型连接中断或返回空内容，本轮未保存，请重试")
        except APITimeoutError:
            raise ModelError("模型请求超时，本轮未保存，请重试", 504) from None
        except OpenAIError as exc:
            # 不把 SDK 异常原文写到日志或响应，避免泄露认证信息和正文。
            logger.warning("Model request failed: %s", type(exc).__name__)
            raise ModelError("模型调用失败，请检查密钥、模型名称、服务地址及网络后重试") from None

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
