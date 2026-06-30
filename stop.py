import os
import psutil

PORT = 8080
PID_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "service.pid")

def get_pid_by_port(port: int) -> int:
    try:
        for conn in psutil.net_connections(kind='inet'):
            if conn.laddr.port == port and conn.status == psutil.CONN_LISTEN:
                return conn.pid
    except Exception:
        pass
    return None

def stop_service():
    pid = None

    # 1. 优先读取 PID 文件
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, "r") as f:
                pid = int(f.read().strip())
        except Exception:
            pass

    # 2. 如果 PID 文件丢失，网络扫描获取
    if not pid:
        pid = get_pid_by_port(PORT)

    if not pid:
        print("[提示] 未发现正在运行的 Uvicorn 服务。")
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
        return

    print(f"正在停止运行在端口 {PORT} 的服务进程 (PID: {pid})...")
    try:
        process = psutil.Process(pid)
        # 递归关闭所有子进程
        for child in process.children(recursive=True):
            child.kill()
        process.kill()
        print("服务已成功停止。")
    except psutil.NoSuchProcess:
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            in_use = s.connect_ex(('127.0.0.1', PORT)) == 0
        if not in_use:
            print("服务已成功停止。")
        else:
            print("[提示] 进程不存在，但端口依然被占用，服务可能已被提前关闭或处于异常状态。")
    except Exception as e:
        print(f"停止服务失败: {e}")

    # 清理遗留文件
    if os.path.exists(PID_FILE):
        try:
            os.remove(PID_FILE)
        except Exception:
            pass

if __name__ == "__main__":
    stop_service()
