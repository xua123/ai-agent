// ==========================================================================
// 全局 State 管理
// ==========================================================================
let state = {
    sessions: [],
    currentSessionId: null,
    models: [],
    currentModelId: null
};

// ==========================================================================
// DOM 元素缓存
// ==========================================================================
const sidebar = document.getElementById("sidebar");
const toggleSidebarBtn = document.getElementById("toggle-sidebar-btn");
const expandSidebarBtn = document.getElementById("expand-sidebar-btn");
const newChatBtn = document.getElementById("new-chat-btn");
const sessionSearchInput = document.getElementById("session-search");
const sessionListContainer = document.getElementById("session-list");

const modelSelectorBtn = document.getElementById("model-selector-btn");
const currentModelNameSpan = document.getElementById("current-model-name");
const modelDropdownMenu = document.getElementById("model-dropdown-menu");

const welcomeScreen = document.getElementById("welcome-screen");
const messagesContainer = document.getElementById("messages-container");
const messagesList = document.getElementById("messages-list");

const messageInput = document.getElementById("message-input");
const sendMessageBtn = document.getElementById("send-message-btn");
const suggestionChips = document.querySelectorAll(".chip");
const themeToggleBtn = document.getElementById("theme-toggle-btn");

// 根据本地缓存初始化加载主题设置
const savedTheme = localStorage.getItem("theme") || "dark";
if (savedTheme === "light") {
    document.body.classList.add("light-theme");
    if (themeToggleBtn) {
        themeToggleBtn.innerHTML = `<i class="fa-regular fa-sun"></i>`;
    }
}

// ==========================================================================
// 初始化引导入口
// ==========================================================================
document.addEventListener("DOMContentLoaded", async () => {
    // 1. 获取模型列表
    await fetchModels();
    // 2. 获取会话历史列表
    await fetchSessions();
    
    // 绑定事件监听
    initEventListeners();
});

// ==========================================================================
// API 服务接口调用
// ==========================================================================
async function fetchModels() {
    try {
        const response = await fetch("/api/models");
        state.models = await response.json();
        if (state.models.length > 0) {
            state.currentModelId = state.models[0].id;
            currentModelNameSpan.innerText = state.models[0].name;
        }
        renderModelsDropdown();
    } catch (e) {
        console.error("加载模型列表失败", e);
    }
}

async function fetchSessions() {
    try {
        const response = await fetch("/api/sessions");
        state.sessions = await response.json();
        
        // 排序：将最新的会话排在上方
        state.sessions.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
        
        renderSessionList();
        
        // 如果有会话历史，默认选中第一个；否则保持欢迎界面
        if (state.sessions.length > 0 && !state.currentSessionId) {
            await selectSession(state.sessions[0].id);
        } else if (state.currentSessionId) {
            await selectSession(state.currentSessionId);
        } else {
            showWelcomeScreen();
        }
    } catch (e) {
        console.error("加载会话历史失败", e);
    }
}

async function createNewSession() {
    try {
        const defaultModel = state.currentModelId || "Qwen/Qwen3.5-35B-A3B";
        const response = await fetch("/api/sessions", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ title: "New Chat", model: defaultModel })
        });
        const newSession = await response.json();
        
        state.currentSessionId = newSession.id;
        await fetchSessions();
        messageInput.focus();
    } catch (e) {
        console.error("创建会话失败", e);
    }
}

async function selectSession(sessionId) {
    state.currentSessionId = sessionId;
    
    // 更新侧边栏高亮状态
    const items = sessionListContainer.querySelectorAll(".session-item");
    items.forEach(item => {
        if (item.dataset.id === sessionId) {
            item.classList.add("active");
            // 更新顶部所选大模型
            const sessionData = state.sessions.find(s => s.id === sessionId);
            if (sessionData) {
                state.currentModelId = sessionData.model;
                const modelInfo = state.models.find(m => m.id === sessionData.model);
                currentModelNameSpan.innerText = modelInfo ? modelInfo.name : sessionData.model;
            }
        } else {
            item.classList.remove("active");
        }
    });

    // 获取会话消息详情
    try {
        const response = await fetch(`/api/sessions/${sessionId}/messages`);
        const messages = await response.json();
        
        if (messages.length === 0) {
            showWelcomeScreen();
        } else {
            hideWelcomeScreen();
            renderMessages(messages);
        }
    } catch (e) {
        console.error("获取会话消息历史失败", e);
    }
}

async function deleteSession(sessionId, event) {
    event.stopPropagation(); // 阻止触发 selectSession
    if (!confirm("确定要删除这个会话吗？")) return;
    
    try {
        await fetch(`/api/sessions/${sessionId}`, { method: "DELETE" });
        if (state.currentSessionId === sessionId) {
            state.currentSessionId = null;
        }
        await fetchSessions();
    } catch (e) {
        console.error("删除会话失败", e);
    }
}

async function renameSession(sessionId, newTitle) {
    if (!newTitle.trim()) return;
    try {
        await fetch(`/api/sessions/${sessionId}/rename`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ title: newTitle })
        });
        await fetchSessions();
    } catch (e) {
        console.error("重命名会话失败", e);
    }
}

async function changeModel(modelId) {
    state.currentModelId = modelId;
    const modelInfo = state.models.find(m => m.id === modelId);
    currentModelNameSpan.innerText = modelInfo ? modelInfo.name : modelId;
    
    if (state.currentSessionId) {
        try {
            await fetch(`/api/sessions/${state.currentSessionId}/model`, {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ model: modelId })
            });
            // 更新本地会话列表状态
            const session = state.sessions.find(s => s.id === state.currentSessionId);
            if (session) session.model = modelId;
        } catch (e) {
            console.error("更新会话绑定的模型失败", e);
        }
    }
}

// ==========================================================================
// 界面渲染方法
// ==========================================================================
function renderModelsDropdown() {
    modelDropdownMenu.innerHTML = "";
    state.models.forEach(model => {
        const option = document.createElement("div");
        option.className = "model-option";
        if (model.id === state.currentModelId) {
            option.classList.add("active");
        }
        option.innerHTML = `
            <span>${model.name}</span>
            ${model.id === state.currentModelId ? '<i class="fa-solid fa-check"></i>' : ''}
        `;
        option.addEventListener("click", () => {
            changeModel(model.id);
            modelDropdownMenu.classList.add("hidden");
        });
        modelDropdownMenu.appendChild(option);
    });
}

function renderSessionList(filterText = "") {
    sessionListContainer.innerHTML = "";
    const filtered = state.sessions.filter(s => 
        s.title.toLowerCase().includes(filterText.toLowerCase())
    );

    filtered.forEach(session => {
        const li = document.createElement("li");
        li.className = "session-item";
        li.dataset.id = session.id;
        if (session.id === state.currentSessionId) {
            li.classList.add("active");
        }
        
        li.innerHTML = `
            <i class="fa-regular fa-comment-dots session-icon"></i>
            <span class="session-title">${escapeHTML(session.title)}</span>
            <div class="session-actions">
                <button class="action-icon-btn rename-btn" title="重命名"><i class="fa-solid fa-pen"></i></button>
                <button class="action-icon-btn delete-btn" title="删除"><i class="fa-regular fa-trash-can"></i></button>
            </div>
        `;
        
        // 绑定单选会话事件
        li.addEventListener("click", () => selectSession(session.id));
        
        // 绑定删除按钮事件
        const delBtn = li.querySelector(".delete-btn");
        delBtn.addEventListener("click", (e) => deleteSession(session.id, e));
        
        // 绑定重命名逻辑
        const renameBtn = li.querySelector(".rename-btn");
        const titleSpan = li.querySelector(".session-title");
        
        const triggerRename = (e) => {
            e.stopPropagation();
            const input = document.createElement("input");
            input.type = "text";
            input.className = "session-rename-input";
            input.value = session.title;
            
            li.replaceChild(input, titleSpan);
            input.focus();
            input.select();
            
            const finishRename = () => {
                const newTitle = input.value;
                if (newTitle.trim() && newTitle !== session.title) {
                    renameSession(session.id, newTitle);
                } else {
                    li.replaceChild(titleSpan, input);
                }
            };
            
            input.addEventListener("blur", finishRename);
            input.addEventListener("keydown", (evt) => {
                if (evt.key === "Enter") {
                    finishRename();
                } else if (evt.key === "Escape") {
                    li.replaceChild(titleSpan, input);
                }
            });
        };
        
        renameBtn.addEventListener("click", triggerRename);
        titleSpan.addEventListener("dblclick", triggerRename);
        
        sessionListContainer.appendChild(li);
    });
}

function renderMessages(messages) {
    messagesList.innerHTML = "";
    messages.forEach(msg => {
        appendMessageBubble(msg.role, msg.content);
    });
    scrollToBottom();
}

function appendMessageBubble(role, content) {
    const row = document.createElement("div");
    row.className = `message-row ${role}`;
    
    const wrapper = document.createElement("div");
    wrapper.className = "message-content-wrapper";
    
    const avatar = document.createElement("div");
    avatar.className = "avatar-block";
    avatar.innerText = role === "user" ? "AX" : "AI";
    
    const body = document.createElement("div");
    body.className = "message-body";
    body.innerHTML = parseMarkdown(content);
    
    wrapper.appendChild(avatar);
    wrapper.appendChild(body);
    row.appendChild(wrapper);
    messagesList.appendChild(row);
    
    // 初始化新渲染的代码块高亮及复制按钮
    row.querySelectorAll("pre code").forEach(block => {
        hljs.highlightElement(block);
    });
    bindCopyButtons(row);
}

// ==========================================
// 消息流式接收逻辑 (Stream Fetch Handler)
// ==========================================
async function submitUserMessage() {
    const text = messageInput.value.trim();
    if (!text) return;
    
    // 如果没有会话，先创建一个会话
    if (!state.currentSessionId) {
        await createNewSession();
    }
    
    const sessionId = state.currentSessionId;
    
    // 1. 清空输入框并缩回大小
    messageInput.value = "";
    messageInput.style.height = "auto";
    sendMessageBtn.disabled = true;
    sendMessageBtn.classList.add("disabled");
    
    // 2. 渲染用户问题
    hideWelcomeScreen();
    appendMessageBubble("user", text);
    scrollToBottom();
    
    // 3. 渲染 AI 空白气泡与加载光标
    const aiRow = document.createElement("div");
    aiRow.className = "message-row assistant";
    
    const aiWrapper = document.createElement("div");
    aiWrapper.className = "message-content-wrapper";
    
    const aiAvatar = document.createElement("div");
    aiAvatar.className = "avatar-block";
    aiAvatar.innerText = "AI";
    
    const aiBody = document.createElement("div");
    aiBody.className = "message-body";
    // 插入流式加载闪烁光标
    aiBody.innerHTML = `<span class="streaming-cursor"><i class="fa-solid fa-circle"></i></span>`;
    
    aiWrapper.appendChild(aiAvatar);
    aiWrapper.appendChild(aiBody);
    aiRow.appendChild(aiWrapper);
    messagesList.appendChild(aiRow);
    scrollToBottom();
    
    let fullResponseText = "";
    
    try {
        const response = await fetch(`/api/sessions/${sessionId}/chat`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ content: text })
        });
        
        if (!response.body) {
            throw new Error("流式输出通道建立失败");
        }
        
        const reader = response.body.getReader();
        const decoder = new TextDecoder("utf-8");
        let buffer = "";
        
        while (true) {
            const { value, done } = await reader.read();
            if (done) break;
            
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n\n");
            // 保留最后一个可能未接收完整的线段在 buffer 中
            buffer = lines.pop();
            
            for (const line of lines) {
                if (line.startsWith("data:")) {
                    const dataStr = line.slice(5).trim();
                    if (dataStr === "[DONE]") {
                        break;
                    }
                    try {
                        const parsed = JSON.parse(dataStr);
                        if (parsed.text) {
                            fullResponseText += parsed.text;
                            // 动态渲染最新的 markdown 解析内容
                            aiBody.innerHTML = parseMarkdown(fullResponseText) + `<span class="streaming-cursor">|</span>`;
                            scrollToBottom();
                        }
                    } catch (err) {
                        // 忽略半解析的 JSON 片段报错
                    }
                }
            }
        }
        
    } catch (e) {
        console.error("对话失败", e);
        fullResponseText += `\n\n❌ **服务通信故障**: 无法连接到本地后端，请检查服务终端日志。`;
    } finally {
        // 去除闪烁光标，并最终高亮代码块
        aiBody.innerHTML = parseMarkdown(fullResponseText);
        aiBody.querySelectorAll("pre code").forEach(block => {
            hljs.highlightElement(block);
        });
        bindCopyButtons(aiRow);
        scrollToBottom();
        
        // 刷新会话历史列表（因为后端可能会自动根据提问修改会话的默认标题）
        await fetchSessions();
    }
}

// ==========================================================================
// 辅助事件绑定和工具函数
// ==========================================================================
function initEventListeners() {
    // 侧边栏折叠/展开
    toggleSidebarBtn.addEventListener("click", () => {
        sidebar.classList.add("hidden");
        expandSidebarBtn.classList.remove("hidden");
    });
    
    expandSidebarBtn.addEventListener("click", () => {
        sidebar.classList.remove("hidden");
        expandSidebarBtn.classList.add("hidden");
    });

    // 新建会话按钮
    newChatBtn.addEventListener("click", createNewSession);

    // 搜索历史会话
    sessionSearchInput.addEventListener("input", (e) => {
        renderSessionList(e.target.value);
    });

    // 顶部下拉框切换模型
    modelSelectorBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        // 重新渲染高亮标志
        renderModelsDropdown();
        modelDropdownMenu.classList.toggle("hidden");
    });

    document.addEventListener("click", () => {
        modelDropdownMenu.classList.add("hidden");
    });

    // 监听输入框打字自适应大小
    messageInput.addEventListener("input", () => {
        messageInput.style.height = "auto";
        messageInput.style.height = `${messageInput.scrollHeight}px`;
        
        const hasText = messageInput.value.trim().length > 0;
        sendMessageBtn.disabled = !hasText;
        if (hasText) {
            sendMessageBtn.classList.remove("disabled");
        } else {
            sendMessageBtn.classList.add("disabled");
        }
    });

    // 输入框回车发送（Shift + Enter 换行）
    messageInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            submitUserMessage();
        }
    });

    // 发送按钮点击
    sendMessageBtn.addEventListener("click", submitUserMessage);

    // 快捷建议卡片点击
    suggestionChips.forEach(chip => {
        chip.addEventListener("click", () => {
            const promptText = chip.dataset.text;
            messageInput.value = promptText;
            messageInput.dispatchEvent(new Event("input"));
            submitUserMessage();
        });
    });

    // 主题切换按钮事件监听
    if (themeToggleBtn) {
        themeToggleBtn.addEventListener("click", () => {
            document.body.classList.toggle("light-theme");
            const isLight = document.body.classList.contains("light-theme");
            localStorage.setItem("theme", isLight ? "light" : "dark");
            
            if (isLight) {
                themeToggleBtn.innerHTML = `<i class="fa-regular fa-sun"></i>`;
            } else {
                themeToggleBtn.innerHTML = `<i class="fa-regular fa-moon"></i>`;
            }
        });
    }
}

function showWelcomeScreen() {
    welcomeScreen.style.display = "flex";
    messagesList.innerHTML = "";
}

function hideWelcomeScreen() {
    welcomeScreen.style.display = "none";
}

function scrollToBottom() {
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

function escapeHTML(str) {
    return str.replace(/[&<>'"]/g, 
        tag => ({
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            "'": '&#39;',
            '"': '&quot;'
        }[tag] || tag)
    );
}

// 绑定复制按钮事件
function bindCopyButtons(container) {
    container.querySelectorAll(".copy-code-btn").forEach(btn => {
        btn.addEventListener("click", () => {
            const pre = btn.closest("pre");
            const code = pre.querySelector("code");
            navigator.clipboard.writeText(code.innerText).then(() => {
                btn.innerHTML = `<i class="fa-solid fa-check"></i> Copied!`;
                setTimeout(() => {
                    btn.innerHTML = `<i class="fa-regular fa-clipboard"></i> Copy code`;
                }, 2000);
            });
        });
    });
}

// 简单轻量级的 Markdown 语法解析器实现 (Markdown Parser Helper)
function parseMarkdown(text) {
    if (!text) return "";
    let html = text;

    // 1. 编码防注入转义（保留 code 格式化以外的代码安全性）
    // 这一步在完整复杂的 Markdown 引擎里有更精细的处理，这里做基础替换
    
    // 2. 解析代码块 ```javascript ... ```
    const codeBlockRegex = /```(\w*)\n([\s\S]*?)\n```/g;
    html = html.replace(codeBlockRegex, (match, lang, code) => {
        const escapedCode = escapeHTML(code.trim());
        const displayLang = lang || "code";
        return `
            <pre>
                <div class="code-header-bar">
                    <span>${displayLang}</span>
                    <button class="copy-code-btn"><i class="fa-regular fa-clipboard"></i> Copy code</button>
                </div>
                <code class="${lang ? 'language-' + lang : ''}">${escapedCode}</code>
            </pre>
        `;
    });

    // 3. 解析行内粗体 **bold**
    html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');

    // 4. 解析段落（以双换行为分界线）
    const paragraphs = html.split(/\n\n+/);
    const parsedParagraphs = paragraphs.map(p => {
        p = p.trim();
        if (!p) return "";
        // 如果已经包裹了 pre 代码块，则不转为段落标签
        if (p.startsWith("<pre>")) return p;
        // 把单换行转为 <br> 换行
        return `<p>${p.replace(/\n/g, "<br>")}</p>`;
    });

    return parsedParagraphs.join("");
}
