"""打包用入口：启动 uvicorn + FastAPI 服务。"""
import sys
import time


def main():
    print(f"[server.py] 进程启动，Python: {sys.executable}", flush=True)
    print(f"[server.py] sys.frozen = {getattr(sys, 'frozen', False)}", flush=True)
    print(f"[server.py] 工作目录: {sys.path[0] if sys.path else 'N/A'}", flush=True)
    t0 = time.time()

    # 预先 import create_app，提前暴露 import 错误（避免 uvicorn 子进程吞掉异常）
    try:
        from novel_agent.api.app import create_app
        # 触发一次 create_app 调用，把所有路由 import 错误在主进程中暴露
        print("[server.py] 预加载 create_app 验证 import 链…", flush=True)
        create_app()
        print(f"[server.py] 预加载完成，耗时 {time.time() - t0:.2f}s", flush=True)
    except Exception as e:
        print(f"[server.py] 预加载失败: {e}", file=sys.stderr, flush=True)
        import traceback
        traceback.print_exc(file=sys.stderr)
        # 不立即退出，让 uvicorn 也能尝试启动并打印更多信息
        time.sleep(2)

    import uvicorn
    print(f"[server.py] 启动 uvicorn，监听 127.0.0.1:8000，总耗时 {time.time() - t0:.2f}s", flush=True)
    uvicorn.run(
        "novel_agent.api.app:create_app",
        factory=True,
        host="127.0.0.1",
        port=8000,
        reload=False,
    )


if __name__ == "__main__":
    main()
