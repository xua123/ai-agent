#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WeWeRSS 订阅源定时抓取、AI 总结与微信推送系统

核心功能：
1. 定时或单次抓取 WeWeRSS-All.opml 中的微信订阅源最新文章；
2. 增量更新：使用 seen_articles.json 记录已抓取的文章，避免重复推送；
3. 大模型摘要：读取项目底部的 .env 文件，使用大语言模型（默认 Qwen/Qwen3.5-35B-A3B）生成多篇文章的简明投资/行业日报；
4. 微信推送：借助已运行的 OpenClaw Gateway 发送每日摘要到你自己的微信上。
"""

import sys
import io

# 强制重定向标准输出，彻底解决 Windows 控制台 GBK 乱码
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import os
import re
import json
import time
import subprocess
from html.parser import HTMLParser

import requests

# ═══════════════════════════════════════════════════════
# 1. 基础配置读取与初始化
# ═══════════════════════════════════════════════════════

# 获取当前脚本所在文件夹路径
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(BASE_DIR)
OPML_PATH = os.path.join(BASE_DIR, "WeWeRSS-All.opml")
SEEN_FILE_PATH = os.path.join(BASE_DIR, "seen_articles.json")
ENV_PATH = os.path.join(PROJECT_DIR, ".env")

# 默认大模型参数（如果 .env 未配置）
DEFAULT_LLM_KEY = ""
DEFAULT_LLM_URL = "https://api-inference.modelscope.cn/v1/"
DEFAULT_LLM_MODEL = "Qwen/Qwen3.5-35B-A3B"

# OpenClaw 配置OPENCLAW_CMD = r"C:\Users\92410\AppData\Roaming\npm\openclaw.cmd"
OPENCLAW_TARGET = "o9cq80zw6ko1R2iWT3v0GiVhjZlw@im.wechat"
NODE_PATH = r"C:\Program Files\nodejs"

def load_env_variables() -> dict:
    """手动解析项目根目录的 .env 文件，防止依赖加载错误。"""
    config = {
        "OPENAI_API_KEY": DEFAULT_LLM_KEY,
        "OPENAI_BASE_URL": DEFAULT_LLM_URL,
        "MODEL_NAME": DEFAULT_LLM_MODEL
    }
    if not os.path.exists(ENV_PATH):
        print(f"[WARN] 未找到 .env 文件: {ENV_PATH}，将使用内置默认配置")
        return config

    with open(ENV_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key in config:
                    config[key] = val
    return config

# ═══════════════════════════════════════════════════════
# 2. HTML 正文纯文本转换与去噪
# ═══════════════════════════════════════════════════════
_SKIP_TAGS = {"script", "style", "noscript"}
class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag.lower() in _SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag.lower() in _SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data):
        if self._skip_depth > 0:
            return
        s = data.strip()
        if s:
            self._parts.append(s)

    def get_text(self) -> str:
        return "\n".join(self._parts)


def html_to_text(html: str) -> str:
    """提取 HTML 的纯文本，并过滤掉末尾的微信交互噪音"""
    p = _TextExtractor()
    p.feed(html)
    text = p.get_text()
    
    # 过滤微信页脚通用噪音
    noise_keywords = [
        "预览时标签不可点",
        "微信扫一扫",
        "轻点两下取消在看",
        "知道了",
        "轻点两下取消赞"
    ]
    lines = text.splitlines()
    clean_lines = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if any(kw in stripped for kw in noise_keywords):
            break  # 碰到页脚噪音直接停止，不再提取之后的内容
        clean_lines.append(stripped)
        
    return "\n".join(clean_lines)


# ═══════════════════════════════════════════════════════
# 3. 抓取与增量控制
# ═══════════════════════════════════════════════════════

def parse_opml(opml_path: str) -> list[dict]:
    import xml.etree.ElementTree as ET
    tree = ET.parse(opml_path)
    root = tree.getroot()
    feeds = []
    for outline in root.iter("outline"):
        url = outline.get("xmlUrl")
        name = outline.get("text", "未知订阅源")
        if url:
            feeds.append({"name": name, "url": url})
    return feeds


_RE_ENTRY  = re.compile(r"<entry>(.*?)</entry>", re.DOTALL)
_RE_TITLE  = re.compile(r"<title[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", re.DOTALL)
_RE_LINK   = re.compile(r'<link\s[^>]*href=["\']([^"\']+)["\']')
_RE_UPDATED = re.compile(r"<(?:updated|published)>(.*?)</(?:updated|published)>")

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

def fetch_first_article_meta(feed_url: str, timeout: int = 20) -> dict | None:
    """拉取 Feed 并以正则鲁棒匹配第一篇文章"""
    try:
        resp = requests.get(feed_url, headers=_BROWSER_HEADERS, timeout=timeout)
        resp.raise_for_status()
    except Exception as e:
        print(f"    [ERR] Feed 抓取失败: {e}")
        return None

    text = resp.content.decode("utf-8", errors="replace")
    m_entry = _RE_ENTRY.search(text)
    if not m_entry:
        return None

    entry_xml = m_entry.group(1)
    
    title = ""
    m_title = _RE_TITLE.search(entry_xml)
    if m_title:
        title = m_title.group(1).strip()
        title = html_to_text(title) or title

    link = ""
    m_link = _RE_LINK.search(entry_xml)
    if m_link:
        link = m_link.group(1).strip()

    published = ""
    m_time = _RE_UPDATED.search(entry_xml)
    if m_time:
        published = m_time.group(1).strip()

    return {
        "title": title or "（无标题）",
        "link": link,
        "published": published or "（未知时间）",
    }


def fetch_wechat_content(url: str, timeout: int = 20) -> str:
    """请求微信原文提取干净的正文"""
    if not url or "mp.weixin.qq.com" not in url:
        return ""
    
    headers = {
        **_BROWSER_HEADERS,
        "Referer": "https://mp.weixin.qq.com/",
    }
    
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
    except Exception as e:
        return f"（微信正文抓取失败: {e}）"

    html = resp.content.decode("utf-8", errors="replace")
    
    # 微信拦截限制检测
    if any(kw in html for kw in ["环境异常", "请在微信客户端打开", "verify.html"]):
        return "（已被微信防爬拦截，无法获取正文）"

    _RE_WX_CONTENT = re.compile(
        r'id=["\']?js_content["\']?[^>]*>([\s\S]{50,})',
        re.IGNORECASE,
    )
    m = _RE_WX_CONTENT.search(html)
    if not m:
        return "（未找到正文容器 js_content）"

    raw = m.group(1)
    return html_to_text(raw)


def load_seen_links() -> set:
    """加载已推送的文章链接集合"""
    if os.path.exists(SEEN_FILE_PATH):
        try:
            with open(SEEN_FILE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                return set(data)
        except Exception:
            pass
    return set()


def save_seen_links(seen_set: set):
    """保存已推送的文章链接"""
    try:
        with open(SEEN_FILE_PATH, "w", encoding="utf-8") as f:
            json.dump(list(seen_set), f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[ERR] 保存已读历史失败: {e}")


# ═══════════════════════════════════════════════════════
# 4. LLM 总结摘要
# ═══════════════════════════════════════════════════════

def summarize_articles_with_llm(new_articles: list, env_config: dict) -> str:
    """调用大模型，对当天所有新文章进行整体的投资与行业观点摘要"""
    if not new_articles:
        return ""

    print(f"📡 正在调用大模型 ({env_config['MODEL_NAME']}) 生成总结摘要...")
    
    # 构造大模型输入上下文
    articles_context = ""
    for idx, art in enumerate(new_articles, 1):
        content_snippet = art["content"][:2500] if art["content"] else "（未能抓取到正文）"
        articles_context += f"【文章 {idx}】\n"
        articles_context += f"标题: {art['title']}\n"
        articles_context += f"来源: {art['feed_name']}\n"
        articles_context += f"链接: {art['link']}\n"
        articles_context += f"正文: {content_snippet}\n"
        articles_context += f"{'='*30}\n\n"

    system_prompt = (
        "你是一个专业的投资研究和商业分析助手。你需要根据提供的一组微信公众号文章内容，"
        "生成一份排版精美、条理清晰的今日研究简报。请严格按照以下格式进行输出：\n\n"
        "🚀 【AI 微信订阅号今日精选简报】\n"
        "📅 生成时间: {current_time}\n\n"
        "─── 📰 核心文章摘要 ───\n"
        "针对每篇文章，用 1-2 句话客观总结其核心观点和关键论据。\n\n"
        "─── 💡 核心观察与综合研判 ───\n"
        "将今日文章中提及的所有关键线索进行高度提炼（例如市场情绪、PCB/半导体等行业趋势、重点资金动向），"
        "并给出一段 150 字以内的综合研判结论。\n\n"
        "请确保语言精练、干货满满，废话和空话一律省去。不要使用复杂的 markdown 表格，适合微信手机端直接阅读。"
    ).replace("{current_time}", time.strftime("%Y-%m-%d %H:%M:%S"))

    user_prompt = f"以下是今天抓取到的新文章数据，请帮我生成总结简报：\n\n{articles_context}"

    payload = {
        "model": env_config["MODEL_NAME"],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.3
    }
    
    headers = {
        "Authorization": f"Bearer {env_config['OPENAI_API_KEY']}",
        "Content-Type": "application/json"
    }
    
    url = env_config["OPENAI_BASE_URL"].rstrip("/") + "/chat/completions"
    
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=60)
        resp.raise_for_status()
        resp_json = resp.json()
        summary = resp_json["choices"][0]["message"]["content"].strip()
        return summary
    except Exception as e:
        print(f"❌ 大模型调用失败: {e}")
        # 如果大模型失败，提供本地降级文本摘要
        fallback_msg = "⚠️ AI 简报生成失败，以下是今日文章目录：\n\n"
        for art in new_articles:
            fallback_msg += f"- {art['feed_name']}: 《{art['title']}》\n  链接: {art['link']}\n"
        return fallback_msg


# ═══════════════════════════════════════════════════════
# 5. 微信推送（通过 OpenClaw）
# ═══════════════════════════════════════════════════════

# OpenClaw 配置
NODE_EXE = r"C:\Program Files\nodejs\node.exe"
OPENCLAW_MJS = r"C:\Users\92410\AppData\Roaming\npm\node_modules\openclaw\openclaw.mjs"
OPENCLAW_TARGET = "o9cq80zw6ko1R2iWT3v0GiVhjZlw@im.wechat"

def push_to_wechat(message_text: str) -> bool:
    """借助 OpenClaw 命令行发送消息给微信自己，带有智能自动分段和重试机制"""
    if not os.path.exists(NODE_EXE) or not os.path.exists(OPENCLAW_MJS):
        print(f"❌ 未找到 Node.js 或 OpenClaw 模块。请检查路径：\n- Node: {NODE_EXE}\n- OpenClaw: {OPENCLAW_MJS}")
        return False

    # 准备环境
    env = os.environ.copy()
    env["PATH"] = f"{NODE_PATH};" + env.get("PATH", "")

    # 定义单个发送函数（带 3 次重试）
    def send_single_chunk(text_chunk: str) -> bool:
        cmd = [
            NODE_EXE,
            OPENCLAW_MJS,
            "message", "send",
            "--channel", "openclaw-weixin",
            "--target", OPENCLAW_TARGET,
            "--message", text_chunk
        ]
        for attempt in range(1, 4):
            try:
                print(f"  📤 正在发送消息片段 (长度: {len(text_chunk)}) [尝试 {attempt}/3]...")
                # shell=False 配合 node.exe 直接执行，保障多行文本（\n）完整传递，不被 Windows CMD 截断
                res = subprocess.run(
                    cmd, env=env, capture_output=True, text=True, shell=False, 
                    encoding="utf-8", errors="replace"
                )
                if res.returncode == 0:
                    print("  ✅ 该片段发送成功！")
                    return True
                else:
                    err_msg = res.stderr.strip() or res.stdout.strip()
                    print(f"  ⚠️ 发送失败 (代码: {res.returncode}): {err_msg}")
            except Exception as e:
                print(f"  ⚠️ 发送异常: {e}")
            if attempt < 3:
                time.sleep(2)
        return False

    # 尝试直接发送整篇
    print(f"📤 尝试发送完整日报 (总长度: {len(message_text)})...")
    if send_single_chunk(message_text):
        print("✅ 微信完整日报推送成功！")
        return True

    # 如果整篇发送失败，执行自动降级分段发送
    print("⚠️ 完整发送失败，启动自动分段发送机制...")
    sections = []
    current_section = []
    
    # 按照换行拆分段落，确保单个分包内容在 600 字符内
    lines = message_text.split("\n")
    for line in lines:
        if "───" in line or len("\n".join(current_section)) > 600:
            if current_section:
                sections.append("\n".join(current_section))
                current_section = []
        current_section.append(line)
    if current_section:
        sections.append("\n".join(current_section))

    all_success = True
    for idx, section in enumerate(sections, 1):
        if not section.strip():
            continue
        print(f"📦 分段 {idx}/{len(sections)} 发送中...")
        # 补上头部标识，方便微信端阅读连续性
        chunk_text = f"【第 {idx} 部分】\n" + section if len(sections) > 1 else section
        success = send_single_chunk(chunk_text)
        if not success:
            all_success = False
        time.sleep(1.5)  # 避免过快发送触发微信速率限制

    if all_success:
        print("✅ 微信分段日报推送成功！")
        return True
    else:
        print("❌ 部分段落发送失败，请检查微信或 OpenClaw Gateway 状态。")
        return False


# ═══════════════════════════════════════════════════════
# 6. 主程序运行逻辑
# ═══════════════════════════════════════════════════════

def job_flow():
    print("=" * 60)
    print(f"🕒 任务启动时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # A. 加载环境与配置
    env_config = load_env_variables()
    if not env_config["OPENAI_API_KEY"]:
        print("❌ 未配置 OPENAI_API_KEY，请检查 .env 文件。")
        return

    # B. 加载历史已推送记录
    seen_links = load_seen_links()
    
    # C. 读取所有订阅源
    if not os.path.exists(OPML_PATH):
        print(f"❌ OPML 文件不存在: {OPML_PATH}")
        return
        
    feeds = parse_opml(OPML_PATH)
    print(f"📖 载入 {len(feeds)} 个订阅源...")

    # D. 抓取新文章
    new_articles = []
    for feed in feeds:
        print(f"  🔍 正在获取 [{feed['name']}] 最新内容...")
        meta = fetch_first_article_meta(feed["url"])
        if not meta:
            continue
            
        link = meta["link"]
        if not link:
            continue
            
        # 判断是否为新文章（去重）
        if link in seen_links:
            print(f"    - 已抓取过: 《{meta['title']}》，跳过")
            continue
            
        print(f"    - 发现新文章: 《{meta['title']}》")
        
        # 抓取正文
        content = fetch_wechat_content(link)
        
        new_articles.append({
            "feed_name": feed["name"],
            "title": meta["title"],
            "link": link,
            "published": meta["published"],
            "content": content
        })

    # E. 如果有新文章，进行大模型总结和微信推送
    if new_articles:
        print(f"\n🔥 发现 {len(new_articles)} 篇新文章，正在整合生成 AI 日报...")
        
        # AI 总结
        summary = summarize_articles_with_llm(new_articles, env_config)
        
        # 微信推送
        pushed = push_to_wechat(summary)
        
        if pushed:
            # 推送成功后，才将新文章的链接存入 seen 记录中，防止中途出错丢失推送
            for art in new_articles:
                seen_links.add(art["link"])
            save_seen_links(seen_links)
    else:
        print("\n☕ 所有订阅源均无新文章更新。")
        
    print("=" * 60)
    print("🏁 抓取周期执行完毕")


def main():
    # 支持命令行参数 --loop 表示循环运行
    if "--loop" in sys.argv:
        # 默认每 2 小时运行一次
        interval_hours = 2
        print(f"🔁 启动循环挂机模式，每 {interval_hours} 小时自动执行一次...")
        while True:
            try:
                job_flow()
            except Exception as e:
                print(f"⚠️ 循环执行出错: {e}")
            print(f"💤 正在等待下一次运行 (将等待 {interval_hours} 小时)...")
            time.sleep(interval_hours * 3600)
    else:
        # 单次执行模式
        job_flow()


if __name__ == "__main__":
    main()
