import os
import sys
import subprocess
import time
import psutil

PORT = 8080
PID_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "service.pid")
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "service.log")

def is_port_in_use(port: int) -> bool:
    """使用 socket 检测端口是否被占用"""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0

def start_service():
    if is_port_in_use(PORT):
        print(f"[提示] 端口 {PORT} 已被占用，服务似乎已经处于运行状态。")
        return

    python_exe = sys.executable
    main_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "net")
    cmd = [python_exe, "-m", "uvicorn", "main:app", "--port", str(PORT)]

    print("正在后台启动 Uvicorn 服务...")
    print(f"   命令: {' '.join(cmd)}")
    print(f"   日志: {LOG_FILE}")

    log_f = open(LOG_FILE, "w", encoding="utf-8")

    if sys.platform == "win32":
        p = subprocess.Popen(
            cmd,
            cwd=main_dir,
            stdout=log_f,
            stderr=log_f,
            creationflags=subprocess.DETACHED_PROCESS,
            close_fds=True
        )
    else:
        p = subprocess.Popen(
            cmd,
            cwd=main_dir,
            stdout=log_f,
            stderr=log_f,
            preexec_fn=os.setsid,
            close_fds=True
        )

    # 稍等一秒，确认服务是否启动成功
    time.sleep(1.5)
    
    # 查找进程 PID
    pid = None
    try:
        for conn in psutil.net_connections(kind='inet'):
            if conn.laddr.port == PORT and conn.status == psutil.CONN_LISTEN:
                pid = conn.pid
                break
    except Exception:
        pass

    if pid:
        # 保存 PID
        with open(PID_FILE, "w") as f:
            f.write(str(pid))
        print("服务已成功启动！")
        print(f"   访问地址: http://127.0.0.1:{PORT}")
        print(f"   进程 PID: {pid}")
    else:
        # 兜底检测端口占用
        if is_port_in_use(PORT):
            print("服务启动成功，但未获取到具体进程 PID。")
            print(f"   访问地址: http://127.0.0.1:{PORT}")
        else:
            print("服务启动失败！请检查 service.log 获取详细日志。")

if __name__ == "__main__":
    start_service()
