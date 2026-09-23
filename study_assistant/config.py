"""把部署配置与业务代码分开；不会向浏览器返回密钥。"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    api_key: str = ""
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-v4-pro"
    timeout: float = 90.0
    sessions_dir: Path = PROJECT_ROOT / "sessions"
    static_dir: Path = PROJECT_ROOT / "static"

    @classmethod
    def from_env(cls) -> "Settings":
        # 优先使用当前项目 .env；没有时兼容原项目上层的 .env。
        # shell 中已有变量优先，load_dotenv 不覆盖它们。
        for directory in (PROJECT_ROOT, *PROJECT_ROOT.parents):
            candidate = directory / ".env"
            if candidate.is_file():
                load_dotenv(candidate, override=False)
                break
        timeout = float(os.getenv("LLM_TIMEOUT", "90"))
        if timeout <= 0 or not timeout < float("inf"):
            raise ValueError("LLM_TIMEOUT 必须是有限正数")
        return cls(
            api_key=(os.getenv("LLM_API_KEY") or os.getenv("DEEPSEEK_API_KEY") or "").strip(),
            base_url=os.getenv("LLM_BASE_URL", "https://api.deepseek.com").strip(),
            model=os.getenv("LLM_MODEL", "deepseek-v4-pro").strip(),
            timeout=timeout,
        )
