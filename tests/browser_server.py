"""浏览器验收专用服务。存储使用临时目录，模型仅输出模拟内容。"""

import asyncio
import json
import tempfile
from pathlib import Path

import uvicorn

from study_assistant.application import create_app
from study_assistant.config import Settings
from study_assistant.llm import ModelError


class BrowserModel:
    def check_ready(self):
        pass

    async def stream(self, messages):
        question = messages[-1]["content"]
        answer = "## 一个小例子\n\n下面是 **Python 函数**：\n\n```python\ndef greet(name):\n    return f'你好，{name}'\n```\n\n试着解释参数的作用。"
        if "注入" in question:
            answer += '\n\n<script>window.injected=true</script><img src=x onerror="window.injected=true">[危险链接](javascript:alert(1))'
        for part in (answer[:18], answer[18:50], answer[50:]):
            await asyncio.sleep(0.5 if "延迟" in question else 0.25)
            yield part
            if "失败" in question:
                raise ModelError("模拟模型连接中断")

    async def close(self):
        pass


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="zhixing-browser-") as directory:
        storage = Path(directory)
        legacy = {"current_session": "2026-09-23_12-22-49", "messages": [{"role": "assistant", "content": "历史字谜记录"}]}
        (storage / "2026-09-23_12-22-49.json").write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
        app = create_app(Settings(api_key="", sessions_dir=storage), model=BrowserModel())
        uvicorn.run(app, host="127.0.0.1", port=8017)
