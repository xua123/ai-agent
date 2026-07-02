import os
import sys
import json
import uuid
import asyncio
import socket
import subprocess
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from fastapi import FastAPI, HTTPException, Body
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import httpx

# 加载父目录中的 .env 文件
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

app = FastAPI(title="Chat Local Replica")

# 允许跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SESSIONS_FILE = os.path.join(os.path.dirname(__file__), "sessions.json")
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
WECHAT_PORT = 4000
WECHAT_DIR = os.path.join(PROJECT_ROOT, "wechat")
WEWE_RSS_APP_DIR = os.path.join(WECHAT_DIR, "wewe-rss-app")
WEWE_RSS_START_SCRIPT = os.path.join(WEWE_RSS_APP_DIR, "scripts", "start-wewe-rss.ps1")
WECHAT_REPORT_SCRIPT = os.path.join(WECHAT_DIR, "start.py")
WECHAT_LOG_DIR = os.path.join(WEWE_RSS_APP_DIR, "logs")


def is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def start_background_process(cmd: list[str], cwd: str, log_name: str) -> int:
    os.makedirs(WECHAT_LOG_DIR, exist_ok=True)
    log_path = os.path.join(WECHAT_LOG_DIR, log_name)
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW

    log_file = open(log_path, "a", encoding="utf-8")
    process = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        creationflags=creationflags,
    )
    return process.pid

# 数据结构定义
class Message(BaseModel):
    id: str
    role: str  # "user" or "assistant"
    content: str
    timestamp: str

class Session(BaseModel):
    id: str
    title: str
    model: str
    messages: List[Message] = []
    created_at: str

# 读取和写入 sessions.json
def load_sessions() -> Dict[str, Any]:
    if not os.path.exists(SESSIONS_FILE):
        return {}
    try:
        with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_sessions(sessions: Dict[str, Any]):
    with open(SESSIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(sessions, f, ensure_ascii=False, indent=2)

# API 路由
@app.get("/api/models")
async def get_models():
    # 默认支持的模型列表
    # 如果用户在环境变量中配置了 MODEL_NAME，将其设为默认首选项，并剔除前导/后导空格
    env_default_model = os.getenv("LLM_MODEL_ID") or os.getenv("MODEL_NAME") or "Qwen/Qwen3.5-35B-A3B"
    env_default_model = env_default_model.strip()
    
    # 默认支持的高额度/免费优质大模型列表
    all_models = [
        {"id": "Qwen/Qwen3.5-35B-A3B", "name": "Qwen 3.5 35B (环境推荐)"},
        {"id": "deepseek-ai/DeepSeek-V4-Flash", "name": "DeepSeek V4 Flash (极速推荐)"},
        {"id": "Qwen/Qwen2.5-72B-Instruct", "name": "Qwen 2.5 72B (超强开源)"},
        {"id": "deepseek-ai/DeepSeek-R1-Distill-Qwen-32B", "name": "DeepSeek R1 32B (推理特化)"},
        {"id": "Qwen/Qwen2.5-Coder-32B-Instruct", "name": "Qwen Coder 32B (编程特化)"}
    ]
    
    # 查找默认配置是否已在列表中，如果有则将其挪至首位，如果没有则以“环境预设”的名称插入到首位
    idx = -1
    for i, m in enumerate(all_models):
        if m["id"] == env_default_model:
            idx = i
            break
            
    if idx != -1:
        m = all_models.pop(idx)
        all_models.insert(0, m)
    else:
        all_models.insert(0, {"id": env_default_model, "name": f"{env_default_model} (环境预设)"})
        
    return all_models

@app.get("/api/sessions")
async def get_sessions_list():
    sessions = load_sessions()
    # 仅返回会话列表元数据，不包含完整的大文本消息列表，提高加载速度
    return [
        {
            "id": s["id"],
            "title": s["title"],
            "model": s["model"],
            "created_at": s["created_at"],
            "message_count": len(s["messages"])
        }
        for s in sessions.values()
    ]

@app.post("/api/sessions")
async def create_session(
    title: str = Body(default="新会话", embed=True),
    model: str = Body(default="Qwen/Qwen3.5-35B-A3B", embed=True)
):
    sessions = load_sessions()
    session_id = f"session_{uuid.uuid4().hex[:8]}"
    from datetime import datetime
    new_session = {
        "id": session_id,
        "title": title,
        "model": model,
        "messages": [],
        "created_at": datetime.now().isoformat()
    }
    sessions[session_id] = new_session
    save_sessions(sessions)
    return new_session

@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    sessions = load_sessions()
    if session_id in sessions:
        del sessions[session_id]
        save_sessions(sessions)
        return {"status": "success"}
    raise HTTPException(status_code=404, detail="Session not found")

@app.put("/api/sessions/{session_id}/rename")
async def rename_session(session_id: str, title: str = Body(..., embed=True)):
    sessions = load_sessions()
    if session_id in sessions:
        sessions[session_id]["title"] = title
        save_sessions(sessions)
        return sessions[session_id]
    raise HTTPException(status_code=404, detail="Session not found")

@app.put("/api/sessions/{session_id}/model")
async def change_session_model(session_id: str, model: str = Body(..., embed=True)):
    sessions = load_sessions()
    if session_id in sessions:
        sessions[session_id]["model"] = model
        save_sessions(sessions)
        return sessions[session_id]
    raise HTTPException(status_code=404, detail="Session not found")

@app.get("/api/sessions/{session_id}/messages")
async def get_session_messages(session_id: str):
    sessions = load_sessions()
    if session_id in sessions:
        return sessions[session_id]["messages"]
    raise HTTPException(status_code=404, detail="Session not found")

# 对话流式推送核心逻辑
@app.post("/api/sessions/{session_id}/chat")
async def chat_session(session_id: str, content: str = Body(..., embed=True)):
    sessions = load_sessions()
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
        
    session = sessions[session_id]
    from datetime import datetime
    
    # 1. 保存用户的消息
    user_msg_id = f"msg_{uuid.uuid4().hex[:8]}"
    user_message = {
        "id": user_msg_id,
        "role": "user",
        "content": content,
        "timestamp": datetime.now().isoformat()
    }
    session["messages"].append(user_message)
    save_sessions(sessions)

    # 准备给大模型调用的历史对话格式
    history = []
    # 限制携带最近的15条历史消息以防 Token 超出
    for msg in session["messages"][:-1]:
        history.append({"role": msg["role"], "content": msg["content"]})
    history.append({"role": "user", "content": content})

    api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1"
    model_name = session["model"].strip()

    # 内部生成器：处理大模型流式调用与兜底本地模拟
    async def chat_generator():
        ai_response_content = ""
        api_success = False
        
        # 尝试调用大模型接口
        if api_key:
            try:
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                }
                payload = {
                    "model": model_name,
                    "messages": history,
                    "stream": True,
                    "temperature": 0.7
                }
                
                # 清洗 base_url 以确保路由正确
                post_url = base_url.rstrip("/") + "/chat/completions"
                
                # 使用 httpx 异步客户端发起流式请求
                async with httpx.AsyncClient() as client:
                    async with client.stream("POST", post_url, json=payload, headers=headers, timeout=30.0) as r:
                        if r.status_code == 200:
                            async for line in r.aiter_lines():
                                api_success = True
                                if not line:
                                    continue
                                if line.startswith("data:"):
                                    data_str = line[5:].strip()
                                    if data_str == "[DONE]":
                                        break
                                    try:
                                        data_json = json.loads(data_str)
                                        delta = data_json["choices"][0]["delta"]
                                        if "content" in delta:
                                            chunk = delta["content"]
                                            ai_response_content += chunk
                                            yield f"data: {json.dumps({'text': chunk})}\n\n"
                                    except Exception:
                                        pass
                        else:
                            error_text = await r.aread()
                            print(f"API 返回错误 (Status {r.status_code}): {error_text.decode('utf-8')}")
            except Exception as e:
                print(f"API 连接异常: {e}")

        # 如果接口调用失败或未配置 Key，使用高质量本地打字机效果进行模拟
        if not api_success:
            print("⚠️ API 调用失败，已切换至本地智能助理演示模式")
            simulated_paragraphs = [
                f"你好！我是本地配置的三国智能助手。由于当前外部大模型 API 配置受限或额度耗尽（Base URL 为 {base_url}），我已启动【本地容错模式】来为你提供应答服务。\n\n",
                f"针对你的提问：**“{content}”**，我的理解与回应如下：\n\n",
                "1. **大模型动态切换验证**：当前会话配置使用的模型是 `" + model_name + "`。如果我们在页面顶部的下拉菜单切换模型，后端在连接成功时会自动调用相应型号的推理 API。\n",
                "2. **会话持久化与状态验证**：你的所有会话记录（包括刚刚的提问和当前的回答）均以 JSON 格式完整保存在本地的 `sessions.json` 文件中。即使你刷新页面，这些聊天历史也会被完整保留。\n",
                "3. **系统功能测试建议**：你可以尝试在左侧点击 **New Chat** 新建另一个会话分支，并分别测试不同的问题和模型。这能帮助你验证多会话管理与大模型隔离调用功能。\n\n",
                "如果你已经充值了对应的 API 额度，请在父目录下的 `.env` 文件中配置正确的 `OPENAI_API_KEY` 与 `OPENAI_BASE_URL`，重新运行服务后即可畅享云端大模型的实时解答！"
            ]
            
            # 模拟流式打字输出，给用户非常流畅的视觉效果
            for paragraph in simulated_paragraphs:
                for char in paragraph:
                    ai_response_content += char
                    yield f"data: {json.dumps({'text': char})}\n\n"
                    # 打字机停顿时间
                    await asyncio.sleep(0.015)
                await asyncio.sleep(0.1)

        # 2. 对话结束后，把助手的回答持久化到会话中
        # 重新读取 sessions 以防流式期间其他会话数据被更新
        latest_sessions = load_sessions()
        if session_id in latest_sessions:
            assistant_msg_id = f"msg_{uuid.uuid4().hex[:8]}"
            assistant_message = {
                "id": assistant_msg_id,
                "role": "assistant",
                "content": ai_response_content,
                "timestamp": datetime.now().isoformat()
            }
            latest_sessions[session_id]["messages"].append(assistant_message)
            
            # 如果会话标题是默认的“新会话”，则根据用户第一次提问内容自动生成一个简短的会话标题
            if latest_sessions[session_id]["title"] == "新会话" or latest_sessions[session_id]["title"] == "New Chat":
                title_preview = content[:15] + "..." if len(content) > 15 else content
                latest_sessions[session_id]["title"] = title_preview

            save_sessions(latest_sessions)

        yield "data: [DONE]\n\n"

    return StreamingResponse(chat_generator(), media_type="text/event-stream")


@app.get("/api/wechat/status")
async def get_wechat_status():
    running = is_port_in_use(WECHAT_PORT)
    return {
        "running": running,
        "port": WECHAT_PORT,
        "dash_url": f"http://127.0.0.1:{WECHAT_PORT}/dash",
        "feeds_url": f"http://127.0.0.1:{WECHAT_PORT}/feeds",
        "opml_exists": os.path.exists(os.path.join(WECHAT_DIR, "WeWeRSS-All.opml")),
        "report_script_exists": os.path.exists(WECHAT_REPORT_SCRIPT),
    }


@app.post("/api/wechat/start")
async def start_wewe_rss_service():
    if is_port_in_use(WECHAT_PORT):
        return {"status": "running", "message": "WeWe RSS 已在运行"}

    if not os.path.exists(WEWE_RSS_START_SCRIPT):
        raise HTTPException(status_code=404, detail=f"未找到启动脚本: {WEWE_RSS_START_SCRIPT}")

    pid = start_background_process(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            WEWE_RSS_START_SCRIPT,
        ],
        cwd=WEWE_RSS_APP_DIR,
        log_name="start-from-ai-agent.log",
    )
    return {"status": "starting", "pid": pid, "message": "WeWe RSS 正在启动"}


@app.post("/api/wechat/report")
async def run_wechat_report():
    if not os.path.exists(WECHAT_REPORT_SCRIPT):
        raise HTTPException(status_code=404, detail=f"未找到日报脚本: {WECHAT_REPORT_SCRIPT}")

    pid = start_background_process(
        [sys.executable, WECHAT_REPORT_SCRIPT],
        cwd=WECHAT_DIR,
        log_name="wechat-report.log",
    )
    return {"status": "started", "pid": pid, "message": "微信公众号日报任务已启动"}

# 导入 Chapter 8 Q&A 助手 Gradio UI 并挂载
try:
    import sys
    import importlib
    parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if parent_dir not in sys.path:
        sys.path.append(parent_dir)
    qa_assistant = importlib.import_module("chapter8.11_Q&A_Assistant")
    demo = qa_assistant.create_gradio_ui()
    import gradio as gr
    app = gr.mount_gradio_app(app, demo, path="/chapter8")
    print("Chapter 8 Q&A Assistant mounted successfully at /chapter8")
except Exception as e:
    print(f"Error mounting chapter8 Gradio app: {e}")

# 挂载静态文件目录，实现 HTML 页面展示
# 如果 static 文件夹不存在，我们在启动时创建它
os.makedirs(os.path.join(os.path.dirname(__file__), "static"), exist_ok=True)
app.mount("/", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static"), html=True), name="static")
