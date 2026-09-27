"""把部署配置与业务代码分开；不会向浏览器返回密钥。"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


# 定位项目根目录，确保配置文件的相对路径正确
PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    # API 密钥
    api_key: str = ""
    # 基础 URL
    base_url: str = ""
    # 模型名称
    model: str = ""
    # 超时时间
    timeout: float = 90.0
    # 会话目录
    sessions_dir: Path = PROJECT_ROOT / "sessions"
    # 静态文件目录
    static_dir: Path = PROJECT_ROOT / "static"

    @classmethod
    def from_env(cls) -> "Settings":
        for directory in (PROJECT_ROOT, *PROJECT_ROOT.parents):
            candidate = directory / ".env"
            if candidate.is_file():
                load_dotenv(candidate, override=False)
                break
        timeout = float(os.getenv("LLM_TIMEOUT", "90"))
        if timeout <= 0 or not timeout < float("inf"):
            raise ValueError("LLM_TIMEOUT 必须是有限正数")
        return cls(
            api_key=(os.getenv("ZHIPU_API_KEY") or "").strip(),
            base_url=os.getenv("ZHIPU_API_URL", "https://open.bigmodel.cn/api/paas/v4/").strip(),
            model=os.getenv("ZHIPU_MODEL", "glm-5.3").strip(),
            timeout=timeout,
        )