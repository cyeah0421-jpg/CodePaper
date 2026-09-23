"""启动入口：运行 python main.py，具体功能位于 study_assistant 包。"""

from study_assistant.application import create_app

app = create_app()

if __name__ == "__main__":
    import uvicorn

    # JSON 存储的锁位于当前进程，第一版始终使用一个 worker。
    uvicorn.run(app, host="127.0.0.1", port=8001)
