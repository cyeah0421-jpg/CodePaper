"""可选真实联调：发送一个极短问题，不写入用户会话、不输出密钥。"""

import asyncio
from dataclasses import replace

from study_assistant.config import Settings
from study_assistant.llm import ModelError, ModelService


async def main():
    service = ModelService(replace(Settings.from_env(), timeout=20))
    try:
        async with asyncio.timeout(30):
            parts = [part async for part in service.stream([
                {"role": "user", "content": "这是一条连接测试。请只回复：连接正常。"},
            ])]
        print(f"真实模型流式请求成功，收到 {len(''.join(parts))} 个正文字符；未写入会话。")
        return 0
    except (ModelError, TimeoutError) as exc:
        print(f"真实模型尚未验证成功：{str(exc) or '总请求时间超过 30 秒'}")
        return 1
    finally:
        await service.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
