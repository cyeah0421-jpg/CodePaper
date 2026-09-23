/* 页面只负责交互与渲染，模型密钥和文件操作全部留在后端。 */
'use strict';

const MODES = {
    code: {
        name: '代码导师', symbol: '</>', title: '把“看懂”变成“会写”',
        description: '从一段代码、一个报错或一个概念开始。一起拆解原理，再用小例子验证理解。',
        placeholder: '粘贴代码、报错信息，或说说你想学习的概念…',
        examples: ['用一个小例子讲解 Python 装饰器', '给我一道列表推导式练习，先不要给答案', '如何读懂一个 FastAPI 接口？'],
        tip: '先预测代码的输出，再运行验证。解释“为什么”比记住答案更有帮助。',
        scope: '支持粘贴代码与文本。本版本不会读取项目文件或运行代码。',
    },
    paper: {
        name: '论文阅读', symbol: '¶', title: '从一段原文，读懂一个想法',
        description: '粘贴摘要、方法或你不理解的段落，一起辨认研究问题、证据与结论。',
        placeholder: '粘贴论文摘要或正文片段，并说明你想了解什么…',
        examples: ['请基于我接下来粘贴的摘要分析研究问题和方法', '帮我区分这段文本的原文结论与可能的推断', '我会粘贴一个公式，请解释符号含义和直觉'],
        tip: '阅读时问自己：作者想解决什么问题？哪些证据支持这个结论？',
        scope: '第一版支持粘贴文本，暂不支持 PDF 上传、联网检索或全文定位。',
    },
    review: {
        name: '复习教练', symbol: '↻', title: '试着回忆，让知识留下来',
        description: '告诉我复习主题，或粘贴学习笔记。每次一道题，根据你的回答继续深入。',
        placeholder: '粘贴复习材料，或告诉我你的复习主题与程度…',
        examples: ['我是 Python 初学者，请一次一题考我函数基础', '根据我接下来粘贴的笔记出题，等我回答再讲解', '考我 HTTP 请求和响应，答错时先给提示'],
        tip: '先不看笔记尝试回答。那些想不起来的地方，就是下一次学习的起点。',
        scope: '复习仅依据当前会话和提供的材料，不读取其他会话，也不自动安排复习。',
    },
    legacy: {
        name: '历史字谜', symbol: '字', title: '保留一段旧时光',
        description: '这是改造前的汉字谜盒记录，可以阅读或删除。新建学习会话即可开始使用知行助手。',
        placeholder: '历史会话只读，请新建学习会话。',
        examples: [], tip: '旧记录保留在原来的 JSON 文件中，读取不会改写它。', scope: '历史字谜会话只读。',
    },
};
const $ = id => document.getElementById(id);
const ui = {
    list: $('recordsList'), messages: $('chatMessages'), input: $('chatInput'),
    newMode: $('newMode'), send: $('btnSend'), create: $('btnNewSession'),
};
// 每个会话拥有自己的历史、草稿和生成状态，不能只用一个全局回答字符串。
const state = {
    sessions: [], currentId: null, cache: new Map(), drafts: new Map(), pending: new Map(),
    busy: false, loading: false, loadVersion: 0, dialogId: null,
};

function showNotice(message = '') {
    $('notice').textContent = message;
    $('notice').hidden = !message;
}

async function api(path, options = {}) {
    const response = await fetch(path, {
        ...options, headers: { 'Content-Type': 'application/json', ...options.headers },
    });
    let result;
    try { result = await response.json(); }
    catch { throw new Error('服务器响应无法读取，请检查服务是否启动'); }
    if (!response.ok || result.code !== 200) throw new Error(result.message || '请求失败');
    return result;
}

function currentSession() {
    return state.cache.get(state.currentId) || state.sessions.find(s => s.id === state.currentId);
}
function currentMode() {
    return MODES[currentSession()?.mode || ui.newMode.value] || MODES.code;
}
function updateSummary(summary) {
    state.sessions = [summary, ...state.sessions.filter(s => s.id !== summary.id)]
        .sort((a, b) => b.updated_at.localeCompare(a.updated_at));
}
function isCurrentBusy() {
    return state.pending.get(state.currentId)?.status === 'generating';
}

function renderRecords() {
    ui.list.replaceChildren();
    $('sessionCount').textContent = state.sessions.length;
    if (!state.sessions.length) {
        const empty = document.createElement('p');
        empty.className = 'records-empty';
        empty.textContent = '还没有学习记录。选一个模式，开始你的第一次探索。';
        ui.list.append(empty);
    }
    for (const session of state.sessions) {
        const item = document.createElement('button');
        item.className = 'record-item' + (session.id === state.currentId ? ' active' : '');
        item.dataset.id = session.id;
        item.setAttribute('aria-current', session.id === state.currentId ? 'true' : 'false');
        const name = document.createElement('span');
        name.className = 'record-name';
        name.textContent = session.name;
        const meta = document.createElement('span');
        meta.className = 'record-meta';
        const mode = document.createElement('span');
        mode.textContent = MODES[session.mode]?.name || '会话';
        const date = document.createElement('span');
        date.textContent = isFinite(Date.parse(session.updated_at))
            ? new Date(session.updated_at).toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' }) : '';
        meta.append(mode, date);
        item.append(name, meta);
        item.addEventListener('click', () => switchSession(session.id).catch(report));
        ui.list.append(item);
    }
}

function chooseExample(text) {
    if (ui.input.disabled) return;
    ui.input.value = text;
    state.drafts.set(state.currentId, text);
    ui.input.focus();
    updateControls();
}

function renderGuide() {
    const mode = currentMode();
    $('modeBadge').textContent = mode.name;
    $('sessionName').textContent = currentSession()?.name || '今天，想弄懂什么？';
    $('guideSymbol').textContent = mode.symbol;
    $('guideTitle').textContent = mode.name;
    $('guideDescription').textContent = mode.description;
    $('learningTip').textContent = mode.tip;
    $('scopeNote').textContent = mode.scope;
    ui.input.placeholder = mode.placeholder;
    $('suggestions').replaceChildren();
    for (const text of mode.examples) {
        const button = document.createElement('button');
        button.className = 'suggestion';
        button.textContent = text;
        button.addEventListener('click', () => chooseExample(text));
        $('suggestions').append(button);
    }
}

function updateControls() {
    const readOnly = Boolean(currentSession()?.read_only);
    const missingHistory = Boolean(state.currentId && !state.cache.has(state.currentId));
    ui.input.disabled = state.loading || missingHistory || isCurrentBusy() || readOnly;
    ui.send.disabled = state.busy || state.loading || missingHistory || readOnly || !ui.input.value.trim();
    ui.send.textContent = state.busy ? '生成中…' : '发送 ↑';
    ui.create.disabled = state.busy;
    $('btnRename').disabled = !state.currentId || missingHistory || readOnly || state.loading || isCurrentBusy();
    $('btnDelete').disabled = !state.currentId || state.loading || isCurrentBusy();
    $('inputHint').textContent = readOnly ? '历史会话只读 · 请新建学习会话' : 'Enter 发送 · Shift + Enter 换行';
    $('generationStatus').textContent = isCurrentBusy()
        ? '正在思考和书写…'
        : state.busy ? '另一段会话正在生成回复，可以继续浏览。' : '';
}

function renderMarkdown(target, content) {
    // 模型输出同样是不可信输入：先解析 Markdown，再清洗 HTML，最后插入 DOM。
    if (!window.marked || !window.DOMPurify) {
        target.textContent = content;
        target.style.whiteSpace = 'pre-wrap';
        return;
    }
    const html = marked.parse(content, { breaks: true, gfm: true });
    target.innerHTML = DOMPurify.sanitize(html, {
        USE_PROFILES: { html: true },
        FORBID_TAGS: ['img', 'video', 'audio', 'iframe', 'form', 'input', 'button', 'style'],
        FORBID_ATTR: ['style', 'id', 'name'],
    });
    target.querySelectorAll('a').forEach(a => {
        a.setAttribute('target', '_blank');
        a.setAttribute('rel', 'noopener noreferrer');
    });
    target.querySelectorAll('pre code').forEach(code => {
        if (window.hljs) hljs.highlightElement(code);
        const text = code.textContent;
        const button = document.createElement('button');
        button.className = 'copy-code';
        button.textContent = '复制代码';
        button.addEventListener('click', async () => {
            try {
                await navigator.clipboard.writeText(text);
                button.textContent = '已复制';
                setTimeout(() => { button.textContent = '复制代码'; }, 1500);
            } catch { showNotice('复制失败，请手动选中代码复制。'); }
        });
        code.parentElement.append(button);
    });
    target.querySelectorAll('table').forEach(table => {
        const wrapper = document.createElement('div');
        wrapper.className = 'table-scroll';
        table.replaceWith(wrapper);
        wrapper.append(table);
    });
}

function messageNode(role, content, status = '') {
    const row = document.createElement('article');
    row.className = 'message-row ' + role;
    const label = document.createElement('div');
    label.className = 'message-label';
    label.textContent = role === 'user' ? '你' : '知行助手';
    const bubble = document.createElement('div');
    bubble.className = 'message-bubble';
    if (role === 'assistant') renderMarkdown(bubble, content || '正在思考…');
    else bubble.textContent = content;
    row.append(label, bubble);
    if (status) {
        const footer = document.createElement('div');
        footer.className = 'message-status' + (status.startsWith('未完成') ? ' failed' : '');
        footer.textContent = status;
        row.append(footer);
    }
    return row;
}

function renderMessages(forceBottom = false) {
    const oldScroll = ui.messages.scrollTop;
    const nearBottom = ui.messages.scrollHeight - oldScroll - ui.messages.clientHeight < 100;
    ui.messages.replaceChildren();
    const session = state.cache.get(state.currentId);
    const pending = state.pending.get(state.currentId);
    if (!session?.messages?.length && !pending) {
        const mode = currentMode();
        const empty = document.createElement('div');
        empty.className = 'empty-state';
        const icon = document.createElement('div');
        icon.className = 'empty-icon'; icon.textContent = mode.symbol;
        const kicker = document.createElement('div');
        kicker.className = 'empty-kicker'; kicker.textContent = 'LEARN · THINK · BUILD';
        const title = document.createElement('h2'); title.textContent = state.loading ? '正在读取会话…' : mode.title;
        const description = document.createElement('p'); description.textContent = mode.description;
        const starters = document.createElement('div'); starters.className = 'starter-grid';
        for (const text of mode.examples.slice(0, 2)) {
            const button = document.createElement('button');
            button.className = 'starter'; button.textContent = text;
            button.addEventListener('click', () => chooseExample(text));
            starters.append(button);
        }
        empty.append(icon, kicker, title, description, starters);
        ui.messages.append(empty);
    }
    for (const message of session?.messages || []) {
        ui.messages.append(messageNode(message.role, message.content));
    }
    if (pending) {
        ui.messages.append(messageNode('user', pending.text));
        ui.messages.append(messageNode('assistant', pending.answer,
            pending.status === 'generating' ? '生成中…' : '未完成 · ' + pending.error));
    }
    if (forceBottom || nearBottom) ui.messages.scrollTop = ui.messages.scrollHeight;
    else ui.messages.scrollTop = oldScroll;
}

function renderPage(forceBottom = false) {
    renderRecords();
    renderGuide();
    renderMessages(forceBottom);
    updateControls();
}

async function refreshList() {
    const result = await api('/api/sessions');
    state.sessions = result.data;
    if (result.message !== '成功') showNotice(result.message);
    renderRecords();
}

async function switchSession(id) {
    state.drafts.set(state.currentId, ui.input.value);
    state.currentId = id;
    const version = ++state.loadVersion;
    const cachedAtStart = state.cache.get(id);
    state.loading = true;
    ui.input.value = state.drafts.get(id) || '';
    $('sessionSidebar').classList.remove('open');
    $('btnMenu').setAttribute('aria-expanded', 'false');
    renderPage(true);
    try {
        const result = await api('/api/sessions/' + encodeURIComponent(id));
        // 旧请求晚到时不覆盖新会话；生成中的会话也不能被旧快照覆盖。
        if (version !== state.loadVersion || state.currentId !== id) return;
        if ((!state.pending.has(id) || !state.cache.has(id)) && state.cache.get(id) === cachedAtStart) {
            state.cache.set(id, result.data);
        }
    } finally {
        if (version === state.loadVersion) {
            state.loading = false;
            renderPage(true);
        }
    }
}

async function createSession() {
    const result = await api('/api/sessions', {
        method: 'POST', body: JSON.stringify({ mode: ui.newMode.value }),
    });
    updateSummary(result.data);
    state.cache.set(result.data.id, { ...result.data, messages: [] });
    await switchSession(result.data.id);
    return result.data.id;
}

function report(error) {
    showNotice(error.message || '操作失败，请重试');
}

async function sendMessage(event) {
    event?.preventDefault();
    const text = ui.input.value.trim();
    if (!text || state.busy || state.loading || currentSession()?.read_only) return;
    if (text.length > 24000) { showNotice('消息最多 24000 字符，请分段发送。'); return; }
    // 第一次 await 之前就设置 busy，避免双击或快速按 Enter 发出两个请求。
    state.busy = true;
    updateControls();
    showNotice();
    let id = state.currentId;
    let baseMessages = [];
    let pending;
    try {
        if (!id) id = await createSession();
        const session = state.cache.get(id);
        baseMessages = [...session.messages];
        pending = { text, answer: '', status: 'generating', error: '' };
        state.pending.set(id, pending);
        state.drafts.set(id, '');
        if (state.currentId === id) ui.input.value = '';
        renderPage(true);
        const response = await fetch('/api/sessions/' + id + '/messages/stream', {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message: text }),
        });
        if (!response.ok) {
            const result = await response.json();
            throw new Error(result.message || '发送失败');
        }
        let done = false;
        await StudyStream.readSSE(response.body, (name, data) => {
            if (name === 'delta' && !done) {
                pending.answer += data.content;
                if (state.currentId === id) renderMessages();
            } else if (name === 'error') {
                throw new Error(data.message);
            } else if (name === 'done') {
                done = true;
                state.cache.set(id, {
                    ...session, ...data.session,
                    messages: [...baseMessages, { role: 'user', content: text }, { role: 'assistant', content: pending.answer }],
                });
                updateSummary(data.session);
                state.pending.delete(id);
            }
        });
        if (!done) throw new Error('连接中断，未收到完成确认');
    } catch (error) {
        // 如果服务器已保存而 done 在网络中丢失，先核对历史，避免重试造成重复。
        let recovered = false;
        if (id && pending) {
            try {
                const result = await api('/api/sessions/' + id);
                const history = result.data.messages;
                if (history.length === baseMessages.length + 2
                    && history.at(-2).role === 'user' && history.at(-2).content === text
                    && history.at(-1).role === 'assistant') {
                    state.cache.set(id, result.data);
                    updateSummary(result.data);
                    state.pending.delete(id);
                    recovered = true;
                }
            } catch { /* 查询失败时保留草稿，用户可刷新核对。 */ }
        }
        if (!recovered) {
            if (pending) {
                pending.status = 'failed';
                pending.error = (error.message || '请求失败') + '；草稿已保留，发送可重试。';
            }
            state.drafts.set(id, text);
            if (state.currentId === id) ui.input.value = text;
            report(error);
        }
    } finally {
        state.busy = false;
        renderPage();
        if (state.currentId === id && !ui.input.disabled) ui.input.focus();
    }
}

async function init() {
    $('chatForm').addEventListener('submit', sendMessage);
    ui.input.addEventListener('input', () => {
        state.drafts.set(state.currentId, ui.input.value);
        updateControls();
    });
    ui.input.addEventListener('keydown', event => {
        if (event.key === 'Enter' && !event.shiftKey && !event.isComposing && event.keyCode !== 229) {
            event.preventDefault();
            sendMessage();
        }
    });
    ui.create.addEventListener('click', async () => {
        if (state.busy) return;
        state.busy = true; updateControls();
        try { showNotice(); await createSession(); }
        catch (error) { report(error); }
        finally { state.busy = false; updateControls(); }
    });
    ui.newMode.addEventListener('change', () => {
        if (!state.currentId) renderPage();
    });
    $('btnMenu').addEventListener('click', () => {
        const open = $('sessionSidebar').classList.toggle('open');
        $('btnMenu').setAttribute('aria-expanded', String(open));
    });
    $('btnRename').addEventListener('click', () => {
        state.dialogId = state.currentId;
        $('renameInput').value = currentSession().name;
        $('renameDialog').showModal();
        $('renameInput').select();
    });
    $('cancelRename').addEventListener('click', () => $('renameDialog').close());
    $('renameForm').addEventListener('submit', async event => {
        event.preventDefault();
        const name = $('renameInput').value.trim();
        if (!name) return;
        const id = state.dialogId;
        try {
            const result = await api('/api/sessions/' + id, { method: 'PATCH', body: JSON.stringify({ name }) });
            updateSummary(result.data);
            Object.assign(state.cache.get(id), result.data);
            $('renameDialog').close();
            renderPage();
        } catch (error) { report(error); $('renameDialog').close(); }
    });
    $('btnDelete').addEventListener('click', () => {
        state.dialogId = state.currentId;
        $('deleteDialog').showModal();
    });
    $('cancelDelete').addEventListener('click', () => $('deleteDialog').close());
    $('deleteForm').addEventListener('submit', async event => {
        event.preventDefault();
        const id = state.dialogId;
        try {
            await api('/api/sessions/' + id, { method: 'DELETE' });
            state.sessions = state.sessions.filter(s => s.id !== id);
            state.cache.delete(id); state.pending.delete(id); state.drafts.delete(id);
            $('deleteDialog').close();
            if (state.currentId === id) {
                state.currentId = null; ui.input.value = ''; ++state.loadVersion;
                if (state.sessions.length) await switchSession(state.sessions[0].id);
            }
            renderPage(true);
        } catch (error) { report(error); $('deleteDialog').close(); }
    });
    renderPage();
    try { await refreshList(); }
    catch (error) { report(error); }
    if (!window.marked || !window.DOMPurify || !window.hljs) {
        showNotice('格式化依赖未加载，暂以纯文本展示。请检查 static/vendor 文件。');
    }
}
init();
