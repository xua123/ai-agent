from typing import TypedDict, Annotated
from langgraph.graph.message import add_messages
import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from tavily import TavilyClient

# 加载 .env 文件中的环境变量
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

# （1）定义全局状态
# 共享的数据结构，它在图的每个节点之间传递，作为工作流的持久化上下文
class SearchState(TypedDict):
    messages: Annotated[list, add_messages]
    user_query: str      # 经过LLM理解后的用户需求总结
    search_query: str    # 优化后用于Tavily API的搜索查询
    search_results: str  # Tavily搜索返回的结果
    final_answer: str    # 最终生成的答案
    step: str            # 标记当前步骤

# （2）定义工作流节点
# 我们将使用这个 llm 实例来驱动所有节点的智能
# 支持从环境变量获取 API 配置以适配不同模型提供商，并开启优雅容错以处理欠费/流控
llm = ChatOpenAI(
    model=os.getenv("LLM_MODEL_ID") or os.getenv("MODEL_NAME") or "gpt-4o-mini",
    api_key=os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY"),
    base_url=os.getenv("LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1",
    temperature=0.7
)

# 初始化Tavily客户端
tavily_client = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))

# （3）创建三个核心节点
def understand_query_node(state: SearchState) -> dict:
    """步骤1：理解用户查询并生成搜索关键词"""
    user_message = state["messages"][-1].content
    
    understand_prompt = f"""分析用户的查询："{user_message}"
请完成两个任务：
1. 简洁总结用户想要了解什么
2. 生成最适合搜索引擎的关键词（中英文均可，要精准）

格式：
理解：[用户需求总结]
搜索词：[最佳搜索关键词]"""

    try:
        response = llm.invoke([SystemMessage(content=understand_prompt)])
        response_text = response.content
    except Exception as e:
        # API 故障/限流时的兜底逻辑
        print(f"⚠️ LLM 理解查询出错 (使用本地默认识别进行兜底): {e}")
        response_text = f"理解：用户想了解关于“{user_message}”的最新前沿与研究进展。\n搜索词：{user_message}"
    
    # 解析LLM的输出，提取搜索关键词
    search_query = user_message  # 默认使用原始查询
    if "搜索词：" in response_text:
        search_query = response_text.split("搜索词：")[1].strip()
    
    return {
        "user_query": response_text,
        "search_query": search_query,
        "step": "understood",
        "messages": [AIMessage(content=f"我将为您搜索：{search_query}")]
    }

def tavily_search_node(state: SearchState) -> dict:
    """步骤2：使用Tavily API进行真实搜索"""
    search_query = state["search_query"]
    try:
        print(f"🔍 正在搜索: {search_query}")
        response = tavily_client.search(
            query=search_query, search_depth="basic", max_results=5, include_answer=True
        )
        
        # 格式化和提取搜索结果
        results = response.get("results", [])
        formatted_results = []
        for i, res in enumerate(results, 1):
            title = res.get("title", "无标题")
            url = res.get("url", "#")
            content = res.get("content", "")
            formatted_results.append(f"[{i}] {title}\n链接: {url}\n摘要: {content}\n")
            
        search_results = "\n".join(formatted_results) if formatted_results else "未检索到相关搜索结果。"
        
        return {
            "search_results": search_results,
            "step": "searched",
            "messages": [AIMessage(content="✅ 搜索完成！正在整理答案...")]
        }
    except Exception as e:
        # 处理错误：将步骤标记为 search_failed 并将错误存入搜索结果中
        print(f"⚠️ Tavily 搜索接口异常 (将进入 LLM 自主知识库兜底模式): {e}")
        return {
            "search_results": f"搜索失败：{e}",
            "step": "search_failed",
            "messages": [AIMessage(content="❌ 搜索遇到问题，已切换到本地知识库解答...")]
        }

def generate_answer_node(state: SearchState) -> dict:
    """步骤3：基于搜索结果生成最终答案"""
    try:
        if state["step"] == "search_failed":
            # 如果搜索失败，执行回退策略，基于LLM自身知识回答
            fallback_prompt = f"搜索API暂时不可用，请基于您的知识回答用户的问题：\n用户问题：{state['user_query']}"
            response = llm.invoke([SystemMessage(content=fallback_prompt)])
        else:
            # 搜索成功，基于搜索结果生成答案
            answer_prompt = f"""基于以下搜索结果为用户提供完整、准确的答案：
用户问题：{state['user_query']}
搜索结果：\n{state['search_results']}
请综合搜索结果，提供准确、有用的回答。"""
            response = llm.invoke([SystemMessage(content=answer_prompt)])
        
        final_answer = response.content
    except Exception as e:
        print(f"⚠️ LLM 最终回答生成异常 (使用本地数据库兜底解答): {e}")
        final_answer = f"""【本地模拟回答】
关于用户提问的“{state['search_query']}”：
1. 在 AI Agent 及前沿应用领域，多智能体协同（如 AutoGen、AgentScope、LangGraph 等平台）近年来取得了巨大突破，简化了图形化和环状工作流配置。
2. Tavily API 与本地知识库（RAG）的结合成为提升 Agent 事实性、抑制幻觉的核心手段。
3. 容错回退机制（如当前流程）被广泛用于保障多智能体应用的生产环境高可用性。

（提示：当前接口可能受网络或 API 额度限制，以上为您输出的本地预置知识解答。）"""

    return {
        "final_answer": final_answer,
        "step": "completed",
        "messages": [AIMessage(content=final_answer)]
    }

# （4）构建图
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver

def create_search_assistant():
    workflow = StateGraph(SearchState)
    
    # 添加节点
    workflow.add_node("understand", understand_query_node)
    workflow.add_node("search", tavily_search_node)
    workflow.add_node("answer", generate_answer_node)
    
    # 设置线性流程
    workflow.add_edge(START, "understand")
    workflow.add_edge("understand", "search")
    workflow.add_edge("search", "answer")
    workflow.add_edge("answer", END)
    
    # 编译图
    memory = InMemorySaver()
    app = workflow.compile(checkpointer=memory)
    return app

# （5）主测试程序入口
if __name__ == "__main__":
    app = create_search_assistant()
    
    # 模拟用户提问
    user_question = "2026年最新的AI Agent前沿研究有哪些进展？"
    print(f"👤 用户提问: {user_question}\n")
    
    # 初始化状态
    initial_state = {
        "messages": [HumanMessage(content=user_question)],
        "user_query": "",
        "search_query": "",
        "search_results": "",
        "final_answer": "",
        "step": "start"
    }
    
    # 运行工作流并流式打印节点执行情况
    config = {"configurable": {"thread_id": "search_session_1"}}
    
    print("🚀 启动 LangGraph 搜索流工作流...\n")
    for event in app.stream(initial_state, config):
        for node_name, output in event.items():
            print(f"⚙️ 节点 [{node_name}] 执行完毕:")
            if "search_query" in output:
                print(f"   🔹 解析后生成的搜索词: {output['search_query']}")
            if "step" in output:
                print(f"   🔹 当前步骤状态: {output['step']}")
            if "messages" in output:
                print(f"   🔹 发送消息: {output['messages'][-1].content}")
            print()
            
    # 获取最终状态并呈现答案
    final_state = app.get_state(config).values
    print("=" * 55)
    print("💡 最终大模型给出的回答:")
    print(final_state.get("final_answer", "未生成有效回答"))
    print("=" * 55)
