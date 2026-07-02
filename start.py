import os
import sys
import subprocess
import time
import psutil

PORT = 8080
PID_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "service.pid")
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "service.log")
AI_AGENT_PYTHON = os.environ.get(
    "AI_AGENT_PYTHON",
    r"C:\Users\92410\.conda\envs\ai_agent\python.exe",
)


def get_python_executable() -> str:
    if os.path.exists(AI_AGENT_PYTHON):
        return AI_AGENT_PYTHON
    return sys.executable

def is_port_in_use(port: int) -> bool:
    """使用 socket 检测端口是否被占用"""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0

def start_service():
    if is_port_in_use(PORT):
        print(f"[提示] 端口 {PORT} 已被占用，服务似乎已经处于运行状态。")
        return

    python_exe = get_python_executable()
    main_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "net")
    cmd = [python_exe, "-m", "uvicorn", "main:app", "--port", str(PORT)]

    print("正在启动 Uvicorn 服务...")
    print(f"   Python: {python_exe}")
    print(f"   访问地址: http://127.0.0.1:{PORT}")
    print("服务日志已实时输出到下方控制台 (按 Ctrl+C 可停止服务)\n" + "-"*50)

    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}

    p = subprocess.Popen(
        cmd,
        cwd=main_dir,
        env=env
    )

    # 保存 PID
    with open(PID_FILE, "w") as f:
        f.write(str(p.pid))

    try:
        p.wait()
    except KeyboardInterrupt:
        print("\n正在停止服务...")
        p.terminate()
        p.wait()
    finally:
        # 清理 PID 文件
        if os.path.exists(PID_FILE):
            try:
                os.remove(PID_FILE)
            except Exception:
                pass
        print("服务已成功停止。")

if __name__ == "__main__":
    start_service()
