from colorama import Fore
from camel.societies import RolePlaying
from camel.utils import print_text_animated
from camel.models import ModelFactory
from camel.types import ModelPlatformType
from dotenv import load_dotenv
import os

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

# 统一获取环境变量并支持 fallback 逻辑
LLM_API_KEY = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
LLM_BASE_URL = os.getenv("LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL")
LLM_MODEL = os.getenv("LLM_MODEL") or os.getenv("MODEL_NAME") or "gpt-4o"

# 根据 Base URL 动态识别模型平台类型以确保兼容性
platform = ModelPlatformType.OPENAI_COMPATIBLE_MODEL
if LLM_BASE_URL:
    if "modelscope" in LLM_BASE_URL:
        platform = ModelPlatformType.MODELSCOPE
    elif "aihubmix" in LLM_BASE_URL or "inferera" in LLM_BASE_URL:
        platform = ModelPlatformType.AIHUBMIX
    elif "api.openai.com" in LLM_BASE_URL:
        platform = ModelPlatformType.OPENAI
else:
    platform = ModelPlatformType.OPENAI

# 创建模型
model = ModelFactory.create(
    model_platform=platform,
    model_type=LLM_MODEL,
    url=LLM_BASE_URL,
    api_key=LLM_API_KEY
)

# 定义协作任务
task_prompt = """
创作一本关于"拖延症心理学"的短篇电子书，目标读者是对心理学感兴趣的普通大众。
要求：
1. 内容科学严谨，基于实证研究
2. 语言通俗易懂，避免过多专业术语
3. 包含实用的改善建议和案例分析
4. 篇幅控制在8000-10000字
5. 结构清晰，包含引言、核心章节和总结
"""

print(Fore.YELLOW + f"协作任务:\n{task_prompt}\n")

# 初始化角色扮演会话
# AI 作家作为 "user"，负责提出写作结构和要求
# AI 心理学家作为 "assistant"，负责提供专业知识和内容
role_play_session = RolePlaying(
    assistant_role_name="心理学家",
    user_role_name="作家",
    task_prompt=task_prompt,
    model=model,
    with_task_specify=False, # 在本例中，我们直接使用给定的task_prompt
)

print(Fore.CYAN + f"具体任务描述:\n{role_play_session.task_prompt}\n")

# 开始协作对话
chat_turn_limit, n = 30, 0

# 兜底本地角色扮演数据（防止 API 欠费/超限导致运行失败）
mock_dialogue = [
    {
        "writer": "你好！作为作家，我很高兴与你合作创作这本关于‘拖延症心理学’的电子书。首先，我们来讨论并拟定这本书的大纲结构吧。我建议分为五个部分：引言、第一章（拖延的本质与类型）、第二章（拖延背后的心理机制）、第三章（战胜拖延的实用策略）、结语。你觉得如何？",
        "psychologist": "你好！这个大纲结构非常清晰且合理。从心理学的角度看，我想在第一章中加入关于‘主动拖延’与‘被动拖延’的区别，并在第二章着重探讨‘情绪调节失败’这一核心机制。接下来我们可以细化每一章的子目录和核心观点。"
    },
    {
        "writer": "非常赞同！情绪调节失败确实是很多读者的痛点。那我们现在开始撰写第一章吧。请你从心理学实证研究的角度，通俗易懂地解释一下为什么人们会明知后果却依然选择拖延？",
        "psychologist": "好的。研究表明，人脑在面临‘即时满足’和‘延迟满足’时，边缘系统和前额叶皮层会发生冲突。拖延并不是因为懒惰，而是一种即时的情绪逃避机制——我们为了逃避当下的焦虑或压力，选择了即时的解脱。这就是拖延的心理学本质。"
    },
    {
        "writer": "这个解释太精辟了！边缘系统与前额叶皮层的冲突非常形象，能让大众读者瞬间理解。现在，请你提供 3 个具体且实用的改善拖延症的方法，作为第三章的核心内容。",
        "psychologist": "当然可以。第一是‘5分钟法则’，通过降低行动门槛来启动前额叶；第二是‘情绪接纳’，不再为拖延自我责备，减轻焦虑；第三是‘时间审计’，记录真实的专注时间，建立可行的反馈。我们可以将这些方法融入电子书的改善建议中。<CAMEL_TASK_DONE>"
    }
]

api_failed = False
input_msg = None

try:
    # 调用 init_chat() 来获得由 AI 生成的初始对话消息
    input_msg = role_play_session.init_chat()
except Exception as e:
    api_failed = True
    print(Fore.RED + f"⚠️ API调用失败或额度不足: {e}")
    print(Fore.YELLOW + "🔄 将自动切换为【本地角色扮演模拟模式】演示协作流程...\n")

if not api_failed:
    while n < chat_turn_limit:
        n += 1
        try:
            # step() 方法驱动一轮完整的对话，AI 用户和 AI 助理各发言一次
            assistant_response, user_response = role_play_session.step(input_msg)
            
            # 检查是否有消息返回，防止对话提前终止
            if assistant_response.msg is None or user_response.msg is None:
                break
            
            print_text_animated(Fore.BLUE + f"作家 (AI User):\n\n{user_response.msg.content}\n")
            print_text_animated(Fore.GREEN + f"心理学家 (AI Assistant):\n\n{assistant_response.msg.content}\n")
            
            # 检查任务完成标志
            if "<CAMEL_TASK_DONE>" in user_response.msg.content or "<CAMEL_TASK_DONE>" in assistant_response.msg.content:
                print(Fore.MAGENTA + "✅ 电子书创作完成！")
                break
            
            # 将助理的回复作为下一轮对话的输入
            input_msg = assistant_response.msg
        except Exception as e:
            api_failed = True
            print(Fore.RED + f"\n⚠️ 对话过程中API调用出错: {e}")
            print(Fore.YELLOW + "🔄 将自动切换为【本地角色扮演模拟模式】继续完成剩余协作...\n")
            break

if api_failed:
    # 模拟完整的拖延症心理学电子书创作对话流
    for turn in mock_dialogue:
        # 每一次循环相当于一次 step：AI User 与 AI Assistant 轮流对话
        print_text_animated(Fore.BLUE + f"作家 (AI User):\n\n{turn['writer']}\n")
        print_text_animated(Fore.GREEN + f"心理学家 (AI Assistant):\n\n{turn['psychologist']}\n")
        n += 1
        if "<CAMEL_TASK_DONE>" in turn['writer'] or "<CAMEL_TASK_DONE>" in turn['psychologist']:
            print(Fore.MAGENTA + "✅ 电子书创作完成！")
            break

print(Fore.YELLOW + f"总共进行了 {n} 轮协作对话")
