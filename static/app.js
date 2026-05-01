// ==================== 全局状态 ====================
let sessionId = null;
let isProcessing = false;
let currentModel = 'moonshotai/kimi-k2.6';
let currentStreamDiv = null;      // 当前流式输出中的消息 DOM
let currentStreamContent = '';    // 当前累积的 markdown 原文
let currentReasoningDiv = null;   // 当前 reasoning 容器 DOM

// ==================== DOM 元素 ====================
const chatContainer = document.getElementById('chatContainer');
const userInput = document.getElementById('userInput');
const sendBtn = document.getElementById('sendBtn');
const modelSelect = document.getElementById('modelSelect');
const fileTree = document.getElementById('fileTree');
const statusDot = document.getElementById('statusDot');
const statusText = document.getElementById('statusText');
const sessionInfo = document.getElementById('sessionInfo');
const iterationBadge = document.getElementById('iterationBadge');
const typingIndicator = document.getElementById('typingIndicator');
const fileModal = document.getElementById('fileModal');
const fileModalTitle = document.getElementById('fileModalTitle');
const fileModalContent = document.getElementById('fileModalContent');
const fileDownloadLink = document.getElementById('fileDownloadLink');
const planContainer = document.getElementById('planContainer');
const planCount = document.getElementById('planCount');
const contextContainer = document.getElementById('contextContainer');
const contextBadge = document.getElementById('contextBadge');

// ==================== 初始化 ====================
modelSelect.addEventListener('change', (e) => {
    currentModel = e.target.value;
});

userInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
});

refreshFiles();

// ==================== 核心功能 ====================

async function sendMessage() {
    const text = userInput.value.trim();
    if (!text || isProcessing) return;

    userInput.value = '';
    addUserMessage(text);
    setProcessing(true);

    try {
        const response = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                session_id: sessionId,
                message: text,
                model: currentModel
            })
        });

        if (!response.ok) {
            const err = await response.json().catch(() => ({ detail: '未知错误' }));
            addErrorMessage(err.detail || '请求失败');
            setProcessing(false);
            return;
        }

        // 读取 SSE 流
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let assistantMessageId = null;

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop() || '';

            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    const dataStr = line.slice(6);
                    if (dataStr === '[DONE]') continue;
                    try {
                        const event = JSON.parse(dataStr);
                        handleSSEEvent(event, assistantMessageId);
                        if (event.session_id) {
                            sessionId = event.session_id;
                            sessionInfo.textContent = `会话: ${sessionId.slice(0, 20)}...`;
                        }
                    } catch (e) {
                        console.error('Parse SSE error:', e, dataStr);
                    }
                }
            }
        }
    } catch (e) {
        addErrorMessage(`网络错误: ${e.message}`);
    } finally {
        resetStreamState();
        setProcessing(false);
        refreshFiles();
        refreshContext();
    }
}

function handleSSEEvent(event, assistantMessageIdRef) {
    const { stage, data } = event;

    switch (stage) {
        case 'thinking':
            iterationBadge.classList.remove('hidden');
            iterationBadge.textContent = `思考中... (轮次 ${data.iteration})`;
            statusText.textContent = 'Agent 思考中...';
            statusDot.className = 'w-2 h-2 rounded-full bg-yellow-500';
            break;

        case 'tool_call':
            iterationBadge.textContent = `执行工具 (${data.count}个)`;
            statusText.textContent = '执行工具...';
            break;

        case 'tool_executing':
            addToolCallCard(data);
            break;

        case 'tool_result':
            updateToolResult(data);
            break;

        case 'plan_created':
            renderPlan(data.plan || []);
            break;

        case 'plan_updated':
            renderPlan(data.plan || []);
            break;

        case 'context_set':
            renderContext(data);
            break;

        case 'context_cleared':
            renderContext(null);
            break;

        case 'server_tool_usage':
            renderServerToolUsage(data.server_tool_use || {});
            break;

        case 'reasoning':
            if (data.reasoning) {
                addReasoningBlock(data.reasoning);
            }
            break;

        case 'stream_content':
            appendStreamChunk(data.chunk || '');
            break;

        case 'final':
            iterationBadge.classList.add('hidden');
            statusText.textContent = '就绪';
            statusDot.className = 'w-2 h-2 rounded-full bg-green-500';
            if (!data.error) {
                // 如果已经有流式消息容器，追加图片并结束；否则新建
                if (currentStreamDiv) {
                    finalizeStreamMessage(data.images);
                } else {
                    addAssistantMessage(data.content, data.images, data.reasoning);
                }
            } else {
                addErrorMessage(data.message || data.error);
            }
            resetStreamState();
            break;

        case 'done':
            iterationBadge.classList.add('hidden');
            statusText.textContent = '就绪';
            statusDot.className = 'w-2 h-2 rounded-full bg-green-500';
            if (data.content) {
                if (currentStreamDiv) {
                    finalizeStreamMessage(data.images);
                } else {
                    addAssistantMessage(data.content, data.images, data.reasoning);
                }
            }
            resetStreamState();
            break;

        case 'error':
            iterationBadge.classList.add('hidden');
            statusText.textContent = '错误';
            statusDot.className = 'w-2 h-2 rounded-full bg-red-500';
            addErrorMessage(data.error || data.message || '未知错误');
            resetStreamState();
            break;
    }
}

// ==================== 消息渲染 ====================

function addUserMessage(text) {
    const div = document.createElement('div');
    div.className = 'fade-in flex items-start gap-3 justify-end';
    div.innerHTML = `
        <div class="max-w-[80%] bg-blue-600 rounded-lg px-4 py-3 text-white">
            <div class="whitespace-pre-wrap">${escapeHtml(text)}</div>
        </div>
        <div class="w-8 h-8 rounded-full bg-gray-600 flex items-center justify-center flex-shrink-0">
            <i class="fa-solid fa-user text-sm"></i>
        </div>
    `;
    chatContainer.appendChild(div);
    scrollToBottom();
}

function addAssistantMessage(content, images = null, reasoning = null) {
    if (!content && (!images || images.length === 0) && !reasoning) return;

    const div = document.createElement('div');
    div.className = 'fade-in flex items-start gap-3';

    let reasoningHtml = '';
    if (reasoning) {
        reasoningHtml = `
            <details class="reasoning-block mb-2">
                <summary class="text-xs text-amber-400 cursor-pointer select-none flex items-center gap-1">
                    <i class="fa-solid fa-lightbulb"></i> 思维链 (${reasoning.length} 字符)
                </summary>
                <div class="mt-1 text-xs text-gray-400 bg-gray-900/50 rounded p-2 border border-gray-700/50 whitespace-pre-wrap font-mono leading-relaxed">${escapeHtml(reasoning)}</div>
            </details>
        `;
    }

    let imagesHtml = '';
    if (images && images.length > 0) {
        imagesHtml = '<div class="flex flex-wrap gap-2 mt-2">';
        for (const img of images) {
            const url = img.image_url?.url || img.url || '';
            if (url.startsWith('data:') || url.startsWith('http')) {
                imagesHtml += `<img src="${url}" class="max-w-xs rounded-lg border border-gray-600" alt="Generated">`;
            }
        }
        imagesHtml += '</div>';
    }

    const rendered = content ? marked.parse(content) : '';

    div.innerHTML = `
        <div class="w-8 h-8 rounded-full bg-blue-600 flex items-center justify-center flex-shrink-0">
            <i class="fa-solid fa-robot text-sm"></i>
        </div>
        <div class="flex-1 bg-gray-800 rounded-lg p-4 border border-gray-700">
            ${reasoningHtml}
            <div class="message-content text-gray-200">${rendered}</div>
            ${imagesHtml}
        </div>
    `;
    chatContainer.appendChild(div);
    highlightCode(div);
    scrollToBottom();
}

// ==================== 流式输出 / Reasoning ====================

function addReasoningBlock(reasoning) {
    if (!reasoning) return;
    // 如果已有 reasoning 容器，更新内容；否则新建
    if (currentReasoningDiv) {
        const textDiv = currentReasoningDiv.querySelector('.reasoning-text');
        const summary = currentReasoningDiv.querySelector('summary');
        if (textDiv) textDiv.textContent = reasoning;
        if (summary) summary.innerHTML = `<i class="fa-solid fa-lightbulb"></i> 思维链 (${reasoning.length} 字符)`;
        return;
    }
    const div = document.createElement('div');
    div.className = 'fade-in flex items-start gap-3';
    div.innerHTML = `
        <div class="w-8 h-8 rounded-full bg-amber-600 flex items-center justify-center flex-shrink-0">
            <i class="fa-solid fa-brain text-sm"></i>
        </div>
        <div class="flex-1 bg-gray-800/80 rounded-lg p-3 border border-amber-700/30">
            <details class="reasoning-block" open>
                <summary class="text-xs text-amber-400 cursor-pointer select-none flex items-center gap-1">
                    <i class="fa-solid fa-lightbulb"></i> 思维链 (${reasoning.length} 字符)
                </summary>
                <div class="reasoning-text mt-1 text-xs text-gray-400 bg-gray-900/50 rounded p-2 border border-gray-700/50 whitespace-pre-wrap font-mono leading-relaxed">${escapeHtml(reasoning)}</div>
            </details>
        </div>
    `;
    chatContainer.appendChild(div);
    currentReasoningDiv = div;
    scrollToBottom();
}

function appendStreamChunk(chunk) {
    if (!chunk) return;
    // 如果没有流式消息容器，先创建一个空的
    if (!currentStreamDiv) {
        const div = document.createElement('div');
        div.className = 'fade-in flex items-start gap-3';
        div.innerHTML = `
            <div class="w-8 h-8 rounded-full bg-blue-600 flex items-center justify-center flex-shrink-0">
                <i class="fa-solid fa-robot text-sm"></i>
            </div>
            <div class="flex-1 bg-gray-800 rounded-lg p-4 border border-gray-700">
                <div class="message-content text-gray-200 stream-rendering"></div>
                <div class="stream-cursor w-2 h-4 bg-blue-400 inline-block ml-0.5 align-middle"></div>
            </div>
        `;
        chatContainer.appendChild(div);
        currentStreamDiv = div;
        currentStreamContent = '';
    }
    currentStreamContent += chunk;
    const contentDiv = currentStreamDiv.querySelector('.message-content');
    const cursor = currentStreamDiv.querySelector('.stream-cursor');
    if (contentDiv) {
        contentDiv.innerHTML = marked.parse(currentStreamContent);
        if (cursor) contentDiv.after(cursor);
        highlightCode(currentStreamDiv);
    }
    scrollToBottom();
}

function finalizeStreamMessage(images = null) {
    if (!currentStreamDiv) return;
    // 移除光标
    const cursor = currentStreamDiv.querySelector('.stream-cursor');
    if (cursor) cursor.remove();
    // 追加图片
    if (images && images.length > 0) {
        const bubble = currentStreamDiv.querySelector('.flex-1');
        if (bubble) {
            let imagesHtml = '<div class="flex flex-wrap gap-2 mt-2">';
            for (const img of images) {
                const url = img.image_url?.url || img.url || '';
                if (url.startsWith('data:') || url.startsWith('http')) {
                    imagesHtml += `<img src="${url}" class="max-w-xs rounded-lg border border-gray-600" alt="Generated">`;
                }
            }
            imagesHtml += '</div>';
            bubble.insertAdjacentHTML('beforeend', imagesHtml);
        }
    }
    currentStreamDiv = null;
    currentStreamContent = '';
}

function resetStreamState() {
    currentStreamDiv = null;
    currentStreamContent = '';
    currentReasoningDiv = null;
}

function addErrorMessage(text) {
    const div = document.createElement('div');
    div.className = 'fade-in flex items-start gap-3';
    div.innerHTML = `
        <div class="w-8 h-8 rounded-full bg-red-600 flex items-center justify-center flex-shrink-0">
            <i class="fa-solid fa-triangle-exclamation text-sm"></i>
        </div>
        <div class="flex-1 bg-red-900/30 border border-red-700 rounded-lg p-3 text-red-300">
            <i class="fa-solid fa-circle-xmark mr-1"></i> ${escapeHtml(text)}
        </div>
    `;
    chatContainer.appendChild(div);
    scrollToBottom();
}

let toolCallCounter = 0;
const activeToolCalls = new Map();

function addToolCallCard(data) {
    toolCallCounter++;
    const id = `tool-${toolCallCounter}`;
    activeToolCalls.set(data.id, id);

    const div = document.createElement('div');
    div.id = id;
    div.className = 'fade-in flex items-start gap-3';

    let args = '';
    try {
        const parsed = typeof data.arguments === 'string' ? JSON.parse(data.arguments) : data.arguments;
        args = JSON.stringify(parsed, null, 2);
    } catch {
        args = String(data.arguments);
    }

    const icon = getToolIcon(data.name);
    const color = getToolColor(data.name);

    div.innerHTML = `
        <div class="w-8 h-8 rounded-full ${color} flex items-center justify-center flex-shrink-0">
            <i class="${icon} text-sm"></i>
        </div>
        <div class="flex-1 bg-gray-800/80 rounded-lg p-3 border border-gray-700/50 tool-card">
            <div class="flex items-center justify-between mb-2">
                <span class="text-sm font-semibold text-gray-300">
                    <span class="${color.replace('bg-', 'text-')}">${data.name}</span>
                </span>
                <span class="text-xs text-gray-500 status-badge">
                    <i class="fa-solid fa-spinner fa-spin mr-1"></i> 执行中...
                </span>
            </div>
            <div class="bg-gray-900 rounded p-2 text-xs text-gray-400 font-mono overflow-x-auto">
                <pre>${escapeHtml(args)}</pre>
            </div>
            <div class="result-area mt-2 hidden"></div>
        </div>
    `;
    chatContainer.appendChild(div);
    scrollToBottom();
}

function updateToolResult(data) {
    const domId = activeToolCalls.get(data.id);
    if (!domId) return;

    const card = document.getElementById(domId);
    if (!card) return;

    const statusBadge = card.querySelector('.status-badge');
    const resultArea = card.querySelector('.result-area');
    const isSuccess = data.result?.success;

    if (statusBadge) {
        if (isSuccess) {
            statusBadge.innerHTML = '<i class="fa-solid fa-check-circle mr-1 text-green-400"></i> <span class="text-green-400">成功</span>';
        } else {
            statusBadge.innerHTML = '<i class="fa-solid fa-circle-xmark mr-1 text-red-400"></i> <span class="text-red-400">失败</span>';
        }
    }

        if (resultArea) {
        resultArea.classList.remove('hidden');
        let summary = '';
        if (data.result) {
            if (data.result.type === 'image') {
                summary = `图片: ${data.result.path} (${formatBytes(data.result.size || 0)})`;
            } else if (data.result.saved_files && data.result.saved_files.length > 0) {
                summary = `已保存: ${data.result.saved_files.join(', ')}`;
            } else if (data.result.saved_file) {
                summary = `已保存: ${data.result.saved_file}`;
            } else if (data.result.path) {
                summary = `路径: ${data.result.path}`;
            } else if (data.result.error) {
                summary = `错误: ${data.result.error}`;
            } else if (data.result.stdout !== undefined) {
                summary = data.result.stdout?.slice(0, 200) || '无输出';
            } else if (data.result.plan) {
                summary = `计划: ${data.result.plan.length} 项任务`;
            } else {
                summary = JSON.stringify(data.result, null, 2).slice(0, 300);
            }
        }
        resultArea.innerHTML = `<div class="text-xs ${isSuccess ? 'text-gray-400' : 'text-red-400'}">${escapeHtml(summary)}</div>`;
    }
}

function getToolIcon(name) {
    const map = {
        'generate_image': 'fa-solid fa-image',
        'generate_video': 'fa-solid fa-film',
        'write_file': 'fa-solid fa-file-pen',
        'read_file': 'fa-solid fa-file-lines',
        'edit_file': 'fa-solid fa-pen-to-square',
        'list_files': 'fa-solid fa-folder-open',
        'execute_command': 'fa-solid fa-terminal',
        'create_plan': 'fa-solid fa-list-check',
        'update_plan': 'fa-solid fa-spinner',
        'set_context': 'fa-solid fa-eye-slash',
        'clear_context': 'fa-solid fa-eraser',
        'get_context_summary': 'fa-solid fa-circle-info',
        'openrouter:web_search': 'fa-solid fa-magnifying-glass',
        'openrouter:web_fetch': 'fa-solid fa-globe',
        'openrouter:datetime': 'fa-solid fa-clock'
    };
    return map[name] || 'fa-solid fa-wrench';
}

function getToolColor(name) {
    const map = {
        'generate_image': 'bg-purple-600',
        'generate_video': 'bg-pink-600',
        'write_file': 'bg-green-600',
        'read_file': 'bg-blue-600',
        'edit_file': 'bg-yellow-600',
        'list_files': 'bg-gray-600',
        'execute_command': 'bg-red-600',
        'create_plan': 'bg-indigo-600',
        'update_plan': 'bg-teal-600',
        'set_context': 'bg-slate-600',
        'clear_context': 'bg-stone-600',
        'get_context_summary': 'bg-zinc-600',
        'openrouter:web_search': 'bg-cyan-600',
        'openrouter:web_fetch': 'bg-sky-600',
        'openrouter:datetime': 'bg-emerald-600'
    };
    return map[name] || 'bg-gray-600';
}

// ==================== Server Tool Usage 提示 ====================

function renderServerToolUsage(serverToolUse) {
    if (!serverToolUse || Object.keys(serverToolUse).length === 0) return;

    const div = document.createElement('div');
    div.className = 'fade-in flex items-start gap-3';

    let items = [];
    if (serverToolUse.web_search_requests) {
        items.push(`<span class="text-cyan-400"><i class="fa-solid fa-magnifying-glass mr-1"></i> 网络搜索 ${serverToolUse.web_search_requests} 次</span>`);
    }
    if (serverToolUse.web_fetch_requests) {
        items.push(`<span class="text-sky-400"><i class="fa-solid fa-globe mr-1"></i> 网页获取 ${serverToolUse.web_fetch_requests} 次</span>`);
    }
    if (serverToolUse.datetime_requests) {
        items.push(`<span class="text-emerald-400"><i class="fa-solid fa-clock mr-1"></i> 获取时间</span>`);
    }
    if (items.length === 0) return;

    div.innerHTML = `
        <div class="w-8 h-8 rounded-full bg-gray-700 flex items-center justify-center flex-shrink-0">
            <i class="fa-solid fa-server text-gray-400 text-sm"></i>
        </div>
        <div class="flex-1 bg-gray-800/60 rounded-lg p-2 border border-gray-700/50">
            <div class="text-xs text-gray-400 mb-1">OpenRouter Server Tools 使用记录</div>
            <div class="flex flex-wrap gap-2 text-xs">
                ${items.join('')}
            </div>
        </div>
    `;
    chatContainer.appendChild(div);
    scrollToBottom();
}

// ==================== 计划面板 ====================

function renderPlan(planItems) {
    if (!planItems || planItems.length === 0) {
        planContainer.innerHTML = '<div class="text-gray-500 text-xs italic">暂无计划</div>';
        planCount.classList.add('hidden');
        return;
    }

    planCount.textContent = planItems.length;
    planCount.classList.remove('hidden');

    let html = '';
    for (const item of planItems) {
        const status = item.status || 'pending';
        const statusLabels = {
            'pending': '待办',
            'in_progress': '进行中',
            'completed': '已完成',
            'failed': '失败'
        };
        const note = item.note ? `<div class="text-xs text-gray-500 mt-0.5 ml-3.5">${escapeHtml(item.note)}</div>` : '';
        html += `
            <div class="plan-item ${status} flex flex-col py-1.5 px-2 rounded text-xs">
                <div class="flex items-center">
                    <span class="plan-status-dot ${status}"></span>
                    <span class="text-gray-300 flex-1">${escapeHtml(item.task)}</span>
                    <span class="text-gray-500 text-[10px] uppercase ml-2">${statusLabels[status] || status}</span>
                </div>
                ${note}
            </div>
        `;
    }
    planContainer.innerHTML = html;
}

// ==================== 文件管理 ====================

async function refreshFiles() {
    try {
        const resp = await fetch('/api/files');
        if (!resp.ok) throw new Error('获取文件列表失败');
        const data = await resp.json();
        renderFileTree(data.entries || [], '');
        document.getElementById('fileCount').textContent = `${data.entries?.length || 0} items`;
    } catch (e) {
        fileTree.innerHTML = `<div class="text-red-400 text-xs">${e.message}</div>`;
    }
}

function renderFileTree(entries, prefix) {
    if (!entries || entries.length === 0) {
        fileTree.innerHTML = '<div class="text-gray-500 text-xs italic">Workspace 为空</div>';
        return;
    }

    let html = '';
    for (const entry of entries) {
        const isDir = entry.type === 'directory';
        const icon = isDir ? 'fa-folder text-yellow-500' : 'fa-file text-gray-400';
        const size = entry.size !== null ? `(${formatBytes(entry.size)})` : '';
        const clickAction = isDir 
            ? `onclick="toggleDir('${entry.name}')"` 
            : `onclick="previewFile('${entry.name}')"`;
        html += `
            <div class="flex items-center gap-2 py-1 px-1 rounded hover:bg-gray-700 cursor-pointer truncate" ${clickAction} title="${entry.name}">
                <i class="fa-solid ${icon} text-xs w-4"></i>
                <span class="truncate">${entry.name}</span>
                <span class="text-gray-600 text-xs ml-auto">${size}</span>
            </div>
        `;
    }
    fileTree.innerHTML = html;
}

function toggleDir(name) {
    // 简单实现：对于目录，这里只作提示；可以扩展为展开子目录
    // 实际使用中，复杂目录结构可以通过 API 递归获取
    console.log('目录:', name);
}

async function previewFile(name) {
    try {
        const resp = await fetch(`/api/files/content?path=${encodeURIComponent(name)}`);
        if (!resp.ok) throw new Error('读取失败');
        const data = await resp.json();

        fileModalTitle.textContent = data.path;
        fileDownloadLink.href = `/api/files/download/${encodeURIComponent(data.path)}`;

        if (data.type === 'image') {
            // 图片直接渲染
            fileModalContent.innerHTML = `<img src="${data.data_url}" class="max-w-full rounded-lg" alt="${data.path}">`;
        } else {
            // 文本内容
            fileModalContent.textContent = data.content;
        }
        fileModal.classList.remove('hidden');
    } catch (e) {
        alert('无法预览文件: ' + e.message);
    }
}

function closeFileModal() {
    fileModal.classList.add('hidden');
}

// ==================== 会话管理 ====================

function newSession() {
    sessionId = null;
    resetStreamState();
    sessionInfo.textContent = '会话: 新会话';
    renderPlan([]);
    renderContext(null);
    chatContainer.innerHTML = `
        <div class="fade-in">
            <div class="flex items-start gap-3">
                <div class="w-8 h-8 rounded-full bg-blue-600 flex items-center justify-center flex-shrink-0">
                    <i class="fa-solid fa-robot text-sm"></i>
                </div>
                <div class="flex-1 bg-gray-800 rounded-lg p-4 border border-gray-700">
                    <div class="message-content text-gray-200">
                        <p>已开启新会话。之前的会话历史已清除。</p>
                    </div>
                </div>
            </div>
        </div>
    `;
}

function clearChat() {
    resetStreamState();
    chatContainer.innerHTML = '';
}

// ==================== 工具函数 ====================

function setProcessing(val) {
    isProcessing = val;
    sendBtn.disabled = val;
    sendBtn.style.opacity = val ? '0.5' : '1';
    typingIndicator.classList.toggle('hidden', !val);
    userInput.disabled = val;
}

function scrollToBottom() {
    chatContainer.scrollTop = chatContainer.scrollHeight;
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function highlightCode(container) {
    container.querySelectorAll('pre code').forEach((block) => {
        hljs.highlightElement(block);
    });
}

function formatBytes(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

// ==================== 隐式上下文面板 ====================

function renderContext(data) {
    if (!data || !data.active) {
        contextContainer.innerHTML = '<div class="text-gray-500 text-xs italic">无活跃上下文</div>';
        contextBadge.classList.add('hidden');
        return;
    }

    contextBadge.textContent = 'ON';
    contextBadge.classList.remove('hidden');
    contextBadge.className = 'text-[10px] px-1.5 py-0.5 rounded bg-indigo-900 text-indigo-300';

    const label = escapeHtml(data.label || data.source || '未知');
    const source = escapeHtml(data.source || '');
    const typeLabel = data.type === 'image' ? '图片' : '文本';
    const size = data.content_length ? `${(data.content_length / 1024).toFixed(1)} KB` : '';

    contextContainer.innerHTML = `
        <div class="bg-indigo-900/20 border border-indigo-800/30 rounded p-2">
            <div class="text-xs font-medium text-indigo-300 truncate" title="${source}">${label}</div>
            <div class="text-[10px] text-gray-500 mt-0.5 flex items-center gap-2">
                <span>${typeLabel}</span>
                <span>${size}</span>
            </div>
        </div>
    `;
}

async function refreshContext() {
    if (!sessionId) {
        renderContext(null);
        return;
    }
    try {
        const resp = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/context`);
        if (!resp.ok) {
            renderContext(null);
            return;
        }
        const data = await resp.json();
        if (data.active) {
            renderContext(data);
        } else {
            renderContext(null);
        }
    } catch (e) {
        renderContext(null);
    }
}

// 点击模态框背景关闭
fileModal.addEventListener('click', (e) => {
    if (e.target === fileModal) closeFileModal();
});

// ==================== 调用日志面板 ====================

const logModal = document.getElementById('logModal');
const logTabs = document.getElementById('logTabs');
const logContent = document.getElementById('logContent');
let currentLogSession = null;
let allLogSessions = [];

function openLogModal() {
    logModal.classList.remove('hidden');
    refreshLogs();
}

function closeLogModal() {
    logModal.classList.add('hidden');
}

async function refreshLogs() {
    logContent.innerHTML = '<div class="text-gray-500 italic">加载中...</div>';
    try {
        // 先获取所有会话列表
        const resp = await fetch('/api/logs');
        if (!resp.ok) throw new Error('获取日志列表失败');
        const data = await resp.json();
        allLogSessions = data.sessions || [];

        // 默认显示当前会话，如果没有则显示第一个
        const targetSid = sessionId || (allLogSessions[0]?.session_id);
        renderLogTabs(targetSid);
        if (targetSid) {
            await loadSessionLogs(targetSid);
        } else {
            logContent.innerHTML = '<div class="text-gray-500 italic">暂无日志记录</div>';
        }
    } catch (e) {
        logContent.innerHTML = `<div class="text-red-400">${e.message}</div>`;
    }
}

function renderLogTabs(activeSid) {
    if (!allLogSessions.length) {
        logTabs.innerHTML = '';
        return;
    }
    let html = '';
    for (const s of allLogSessions.slice(0, 10)) {
        const isActive = s.session_id === activeSid;
        html += `
            <button onclick="switchLogSession('${s.session_id}')"
                class="px-3 py-2 whitespace-nowrap border-b-2 transition ${isActive ? 'border-blue-500 text-blue-400 bg-gray-700/50' : 'border-transparent text-gray-400 hover:text-gray-200'}">
                ${escapeHtml(s.session_id.slice(0, 16))}...
            </button>
        `;
    }
    logTabs.innerHTML = html;
}

async function switchLogSession(sid) {
    currentLogSession = sid;
    renderLogTabs(sid);
    await loadSessionLogs(sid);
}

async function loadSessionLogs(sid) {
    logContent.innerHTML = '<div class="text-gray-500 italic">加载中...</div>';
    try {
        const resp = await fetch(`/api/logs/${encodeURIComponent(sid)}`);
        if (!resp.ok) throw new Error('获取日志失败');
        const data = await resp.json();
        renderLogs(data.logs || []);
    } catch (e) {
        logContent.innerHTML = `<div class="text-red-400">${e.message}</div>`;
    }
}

function renderLogs(logs) {
    if (!logs.length) {
        logContent.innerHTML = '<div class="text-gray-500 italic">该会话暂无日志</div>';
        return;
    }
    let html = '';
    for (const entry of logs) {
        html += renderLogEntry(entry);
    }
    logContent.innerHTML = html;
}

function renderLogEntry(entry) {
    const type = entry.type || 'unknown';
    const dt = entry._dt ? entry._dt.split('T')[1]?.slice(0, 12) || entry._dt : '';
    const timeTag = `<span class="text-gray-600 text-xs mr-2">[${dt}]</span>`;

    if (type === 'llm_call') {
        const hasError = entry.error;
        const usage = entry.usage || {};
        const usageStr = usage.input_tokens ? `in=${usage.input_tokens} out=${usage.output_tokens}` : '';
        const summary = entry.response_summary || {};
        return `
            <div class="border-l-2 ${hasError ? 'border-red-500' : 'border-blue-500'} pl-3 py-1">
                <div class="flex items-center gap-2">
                    ${timeTag}
                    <span class="text-blue-400 text-xs font-semibold">LLM</span>
                    <span class="text-gray-500 text-xs">${entry.model}</span>
                    <span class="text-gray-600 text-xs">${entry.duration_ms?.toFixed(0)}ms</span>
                    ${usageStr ? `<span class="text-gray-600 text-xs ml-auto">${usageStr}</span>` : ''}
                </div>
                ${hasError ? `<div class="text-red-400 text-xs mt-1">${escapeHtml(entry.error)}</div>` : ''}
                ${summary.tool_calls_count ? `<div class="text-gray-500 text-xs mt-0.5">工具调用: ${summary.tool_calls_count}个</div>` : ''}
            </div>
        `;
    }

    if (type === 'tool_call') {
        const hasError = entry.error;
        const toolName = escapeHtml(entry.tool_name || '');
        const args = JSON.stringify(entry.arguments || {}, null, 2);
        const preview = entry.result_preview || {};
        let resultHtml = '';
        if (hasError) {
            resultHtml = `<div class="text-red-400 text-xs">${escapeHtml(hasError)}</div>`;
        } else if (preview.error) {
            resultHtml = `<div class="text-red-400 text-xs">${escapeHtml(preview.error)}</div>`;
        } else if (preview.saved_files) {
            resultHtml = `<div class="text-green-400 text-xs">已保存: ${preview.saved_files.join(', ')}</div>`;
        } else if (preview.saved_file) {
            resultHtml = `<div class="text-green-400 text-xs">已保存: ${preview.saved_file}</div>`;
        } else if (preview.path) {
            resultHtml = `<div class="text-gray-400 text-xs">路径: ${preview.path}</div>`;
        } else {
            resultHtml = `<div class="text-gray-400 text-xs">success=${preview.success}</div>`;
        }
        return `
            <div class="border-l-2 ${hasError ? 'border-red-500' : 'border-green-500'} pl-3 py-1">
                <div class="flex items-center gap-2">
                    ${timeTag}
                    <span class="text-green-400 text-xs font-semibold">TOOL</span>
                    <span class="text-gray-300 text-xs">${toolName}</span>
                    <span class="text-gray-600 text-xs">${entry.duration_ms?.toFixed(0)}ms</span>
                </div>
                <details class="mt-1">
                    <summary class="text-gray-500 text-xs cursor-pointer hover:text-gray-300">参数</summary>
                    <pre class="text-gray-400 text-xs mt-1 bg-gray-900 rounded p-1.5 overflow-x-auto">${escapeHtml(args)}</pre>
                </details>
                ${resultHtml}
            </div>
        `;
    }

    if (type === 'error') {
        return `
            <div class="border-l-2 border-red-500 pl-3 py-1 bg-red-900/10 rounded">
                <div class="flex items-center gap-2">
                    ${timeTag}
                    <span class="text-red-400 text-xs font-semibold">ERROR</span>
                    <span class="text-gray-500 text-xs">${escapeHtml(entry.stage || '')}</span>
                </div>
                <div class="text-red-300 text-xs mt-1">${escapeHtml(entry.error || '')}</div>
            </div>
        `;
    }

    // fallback
    return `
        <div class="border-l-2 border-gray-600 pl-3 py-1">
            <div class="flex items-center gap-2">
                ${timeTag}
                <span class="text-gray-400 text-xs">${escapeHtml(type)}</span>
            </div>
            <pre class="text-gray-500 text-xs mt-1">${escapeHtml(JSON.stringify(entry, null, 2))}</pre>
        </div>
    `;
}

// 点击日志模态框背景关闭
logModal.addEventListener('click', (e) => {
    if (e.target === logModal) closeLogModal();
});
