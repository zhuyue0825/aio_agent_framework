from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .config import AgentConfig
from .runtime import AgentRuntime
from .sandbox import SandboxClient
from .tools import build_default_tools
from .trace import TraceLogger
from .approval import ApprovalPolicy


HTML = r"""<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>AIO Agent Framework</title>
  <style>
    :root { --bg:#f5f6f8; --panel:#fff; --line:#dfe2e7; --line-strong:#c9ced6; --text:#1f2329; --muted:#646a73; --soft:#eef2f7; --primary:#1456f0; --primary-dark:#0f45c7; --danger:#d92d20; --code:#101828; --radius:8px; }
    * { box-sizing: border-box; }
    body { margin: 0; font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: var(--bg); color: var(--text); height: 100vh; overflow: hidden; }
    button, textarea { font: inherit; }
    button { border: 1px solid var(--line-strong); border-radius: 7px; background: #fff; color: var(--text); cursor: pointer; height: 36px; padding: 0 12px; }
    button:hover { background: #f8fafc; }
    button.primary { background: var(--primary); border-color: var(--primary); color: #fff; }
    button.primary:hover { background: var(--primary-dark); }
    button.icon { width: 34px; padding: 0; display: inline-flex; align-items: center; justify-content: center; flex: 0 0 auto; }
    button:disabled { opacity: .55; cursor: not-allowed; }
    .app { display: grid; grid-template-columns: 280px minmax(0, 1fr); height: 100vh; }
    .sidebar { background: #f0f2f5; border-right: 1px solid var(--line); display: flex; flex-direction: column; min-width: 0; }
    .brand { height: 60px; padding: 14px 16px; border-bottom: 1px solid var(--line); display: flex; align-items: center; justify-content: space-between; gap: 10px; }
    .brand-title { font-weight: 700; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .sidebar-actions { padding: 12px; display: grid; grid-template-columns: 1fr auto; gap: 8px; }
    .chat-list { padding: 0 8px 12px; overflow: auto; flex: 1; }
    .chat-item { width: 100%; height: auto; min-height: 42px; text-align: left; margin: 2px 0; padding: 8px 10px; border-color: transparent; background: transparent; display: grid; gap: 2px; }
    .chat-item:hover { background: #e8edf3; }
    .chat-item.active { background: #dfe8ff; border-color: #c9d8ff; }
    .chat-title { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 600; }
    .chat-time { color: var(--muted); font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .main { min-width: 0; display: flex; flex-direction: column; background: var(--panel); }
    .topbar { min-height: 60px; border-bottom: 1px solid var(--line); padding: 10px 18px; display: flex; align-items: center; justify-content: space-between; gap: 14px; }
    .status { display: flex; align-items: center; gap: 8px; min-width: 0; flex-wrap: wrap; }
    .pill { display: inline-flex; align-items: center; gap: 6px; max-width: 340px; height: 28px; padding: 0 9px; border: 1px solid var(--line); border-radius: 7px; color: var(--muted); background: #fff; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .pill strong { color: var(--text); font-weight: 600; overflow: hidden; text-overflow: ellipsis; }
    .top-actions { display: flex; align-items: center; gap: 8px; flex: 0 0 auto; }
    .messages { flex: 1; overflow: auto; padding: 24px 18px 18px; }
    .thread { max-width: 900px; margin: 0 auto; display: grid; gap: 18px; }
    .empty { min-height: 56vh; display: grid; align-content: center; justify-items: center; text-align: center; color: var(--muted); gap: 14px; }
    .empty-title { color: var(--text); font-size: 22px; font-weight: 700; }
    .quick-prompts { width: min(760px, 100%); display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
    .quick-prompts button { height: auto; min-height: 48px; text-align: left; padding: 10px 12px; line-height: 1.35; background: #fff; }
    .message { display: grid; grid-template-columns: 34px minmax(0, 1fr); gap: 12px; align-items: start; }
    .avatar { width: 34px; height: 34px; border-radius: 7px; background: var(--soft); border: 1px solid var(--line); display: flex; align-items: center; justify-content: center; color: var(--muted); font-weight: 700; user-select: none; }
    .message.user .avatar { background: #e8f0ff; color: #174ea6; border-color: #cfe0ff; }
    .message.assistant .avatar { background: #eefaf3; color: #16794c; border-color: #d3f0df; }
    .message.error .avatar { background: #fff0ed; color: var(--danger); border-color: #ffd5cc; }
    .bubble { min-width: 0; border: 1px solid var(--line); border-radius: var(--radius); padding: 12px 14px; background: #fff; }
    .message.user .bubble { background: #f8fbff; }
    .message.error .bubble { color: #7a271a; background: #fff7f5; border-color: #ffd5cc; }
    .role { color: var(--muted); font-size: 12px; margin-bottom: 6px; display: flex; align-items: center; gap: 8px; }
    .content { white-space: pre-wrap; overflow-wrap: anywhere; }
    pre.inline-json { margin: 8px 0 0; max-height: 360px; overflow: auto; color: #f9fafb; background: var(--code); border-radius: 7px; padding: 12px; white-space: pre-wrap; overflow-wrap: anywhere; }
    .meta { color: var(--muted); font-size: 12px; margin-top: 8px; }
    .typing { display: inline-flex; gap: 4px; align-items: center; }
    .typing span { width: 6px; height: 6px; border-radius: 50%; background: #98a2b3; animation: pulse 1.2s infinite ease-in-out; }
    .typing span:nth-child(2) { animation-delay: .15s; }
    .typing span:nth-child(3) { animation-delay: .3s; }
    @keyframes pulse { 0%,80%,100% { opacity: .35; transform: translateY(0); } 40% { opacity: 1; transform: translateY(-2px); } }
    .composer-wrap { border-top: 1px solid var(--line); background: #fff; padding: 14px 18px 18px; }
    .composer { max-width: 900px; margin: 0 auto; display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 10px; align-items: end; }
    textarea { width: 100%; min-height: 52px; max-height: 180px; resize: none; border: 1px solid var(--line-strong); border-radius: var(--radius); padding: 12px; outline: none; line-height: 1.45; }
    textarea:focus { border-color: var(--primary); box-shadow: 0 0 0 3px rgba(20, 86, 240, .12); }
    .hint { max-width: 900px; margin: 8px auto 0; color: var(--muted); font-size: 12px; display: flex; justify-content: space-between; gap: 10px; }
    .mobile-sidebar-toggle { display: none; }
    @media (max-width: 800px) {
      body { overflow: auto; }
      .app { grid-template-columns: 1fr; min-height: 100vh; height: auto; }
      .sidebar { display: none; position: fixed; z-index: 10; inset: 0 auto 0 0; width: min(310px, 86vw); box-shadow: 0 20px 50px rgba(15, 23, 42, .22); }
      .sidebar.open { display: flex; }
      .mobile-sidebar-toggle { display: inline-flex; }
      .topbar { align-items: flex-start; }
      .quick-prompts { grid-template-columns: 1fr; }
      .composer { grid-template-columns: 1fr; }
      .composer button.primary { width: 100%; }
      .hint { display: block; }
    }
  </style>
</head>
<body>
  <div class="app">
    <aside class="sidebar" id="sidebar">
      <div class="brand">
        <div class="brand-title">AIO Agent</div>
        <button class="icon" id="collapseSidebar" title="关闭侧栏">×</button>
      </div>
      <div class="sidebar-actions">
        <button class="primary" id="newChat">新对话</button>
        <button class="icon" id="deleteChat" title="删除当前对话">⌫</button>
      </div>
      <div class="chat-list" id="chatList"></div>
    </aside>
    <main class="main">
      <div class="topbar">
        <div class="status">
          <button class="icon mobile-sidebar-toggle" id="openSidebar" title="打开侧栏">☰</button>
          <span class="pill">Sandbox <strong id="sandbox">loading</strong></span>
          <span class="pill">Model <strong id="model">unknown</strong></span>
          <span class="pill">Steps <strong id="steps">-</strong></span>
          <span class="pill">Trace <strong id="trace">disabled</strong></span>
        </div>
        <div class="top-actions">
          <button id="toolDemo">工具 Demo</button>
          <button id="clearChat">清空</button>
        </div>
      </div>
      <section class="messages" id="messages"><div class="thread" id="thread"></div></section>
      <div class="composer-wrap">
        <div class="composer">
          <textarea id="prompt" placeholder="给 Agent 一个任务，比如：列出沙箱文件，读 hello.py，并总结现在有哪些演示文件"></textarea>
          <button class="primary" id="send">发送</button>
        </div>
        <div class="hint">
          <span>Enter 发送，Shift+Enter 换行。对话只保存在当前浏览器 localStorage。</span>
          <span id="keyState">Model key: unknown</span>
        </div>
      </div>
    </main>
  </div>
  <script>
    const STORAGE_KEY = 'aio-agent-framework-chats-v2';
    const els = {
      sidebar: document.getElementById('sidebar'),
      chatList: document.getElementById('chatList'),
      thread: document.getElementById('thread'),
      messages: document.getElementById('messages'),
      prompt: document.getElementById('prompt'),
      send: document.getElementById('send'),
      toolDemo: document.getElementById('toolDemo'),
      clearChat: document.getElementById('clearChat'),
      deleteChat: document.getElementById('deleteChat'),
      newChat: document.getElementById('newChat'),
      sandbox: document.getElementById('sandbox'),
      model: document.getElementById('model'),
      steps: document.getElementById('steps'),
      trace: document.getElementById('trace'),
      keyState: document.getElementById('keyState'),
      openSidebar: document.getElementById('openSidebar'),
      collapseSidebar: document.getElementById('collapseSidebar'),
    };
    let state = loadState();
    let busy = false;

    function uid() { return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`; }
    function nowLabel(ts = Date.now()) { return new Date(ts).toLocaleString([], {month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit'}); }
    function defaultChat() {
      return {
        id: uid(),
        title: '新对话',
        createdAt: Date.now(),
        updatedAt: Date.now(),
        messages: [{role: 'assistant', content: '我可以通过 AIO Sandbox 执行 shell、读写文件、操作浏览器。现在可以像聊天一样给我任务。', createdAt: Date.now()}],
      };
    }
    function loadState() {
      try {
        const parsed = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null');
        if (parsed && Array.isArray(parsed.chats) && parsed.chats.length) return parsed;
      } catch (err) { console.warn(err); }
      const chat = defaultChat();
      return {currentId: chat.id, chats: [chat]};
    }
    function saveState() { localStorage.setItem(STORAGE_KEY, JSON.stringify(state)); }
    function currentChat() {
      let chat = state.chats.find(item => item.id === state.currentId);
      if (!chat) {
        chat = state.chats[0] || defaultChat();
        if (!state.chats.length) state.chats.push(chat);
        state.currentId = chat.id;
      }
      return chat;
    }
    function setCurrent(id) { state.currentId = id; saveState(); render(); els.sidebar.classList.remove('open'); }
    function createChat() { const chat = defaultChat(); state.chats.unshift(chat); state.currentId = chat.id; saveState(); render(); els.prompt.focus(); }
    function deleteCurrentChat() {
      if (state.chats.length <= 1) {
        const chat = currentChat();
        chat.title = '新对话';
        chat.messages = [];
      } else {
        state.chats = state.chats.filter(chat => chat.id !== state.currentId);
        state.currentId = state.chats[0].id;
      }
      saveState();
      render();
    }
    function clearCurrentChat() {
      const chat = currentChat();
      chat.messages = [];
      chat.title = '新对话';
      chat.updatedAt = Date.now();
      saveState();
      render();
    }
    function addMessage(role, content, meta = {}) {
      const chat = currentChat();
      const message = {id: uid(), role, content, createdAt: Date.now(), ...meta};
      chat.messages.push(message);
      chat.updatedAt = message.createdAt;
      if (role === 'user' && (chat.title === '新对话' || !chat.title)) chat.title = content.replace(/\s+/g, ' ').slice(0, 28) || '新对话';
      saveState();
      render();
      return message;
    }
    function updateMessage(id, patch) {
      const chat = currentChat();
      const message = chat.messages.find(item => item.id === id);
      if (message) Object.assign(message, patch);
      chat.updatedAt = Date.now();
      saveState();
      render();
    }
    function render() { renderChatList(); renderThread(); }
    function renderChatList() {
      els.chatList.innerHTML = '';
      const sorted = [...state.chats].sort((a, b) => b.updatedAt - a.updatedAt);
      for (const chat of sorted) {
        const btn = document.createElement('button');
        btn.className = `chat-item${chat.id === state.currentId ? ' active' : ''}`;
        btn.addEventListener('click', () => setCurrent(chat.id));
        const title = document.createElement('div');
        title.className = 'chat-title';
        title.textContent = chat.title || '新对话';
        const time = document.createElement('div');
        time.className = 'chat-time';
        time.textContent = `${nowLabel(chat.updatedAt)} · ${chat.messages.length} 条`;
        btn.append(title, time);
        els.chatList.appendChild(btn);
      }
    }
    function renderThread() {
      const chat = currentChat();
      els.thread.innerHTML = '';
      if (!chat.messages.length) {
        const empty = document.createElement('div');
        empty.className = 'empty';
        const title = document.createElement('div');
        title.className = 'empty-title';
        title.textContent = '开始一个 AIO Sandbox 对话';
        const sub = document.createElement('div');
        sub.textContent = '适合验证文件、命令、浏览器和简单脚本任务。';
        const quick = document.createElement('div');
        quick.className = 'quick-prompts';
        ['列出沙箱 /home/gem 下的文件，并按用途分类总结', '创建一个 Python 脚本统计 data.txt 的水果数量，然后运行它', '打开 https://example.com，截图，并告诉我页面标题', '写一个 web_demo.txt，再读出来确认内容'].forEach(text => {
          const btn = document.createElement('button');
          btn.textContent = text;
          btn.addEventListener('click', () => { els.prompt.value = text; els.prompt.focus(); });
          quick.appendChild(btn);
        });
        empty.append(title, sub, quick);
        els.thread.appendChild(empty);
        return;
      }
      for (const message of chat.messages) els.thread.appendChild(messageNode(message));
      requestAnimationFrame(() => { els.messages.scrollTop = els.messages.scrollHeight; });
    }
    function messageNode(message) {
      const wrap = document.createElement('article');
      wrap.className = `message ${message.role}`;
      const avatar = document.createElement('div');
      avatar.className = 'avatar';
      avatar.textContent = message.role === 'user' ? '你' : message.role === 'error' ? '!' : 'AI';
      const bubble = document.createElement('div');
      bubble.className = 'bubble';
      const role = document.createElement('div');
      role.className = 'role';
      role.textContent = message.role === 'user' ? '你' : message.role === 'error' ? '错误' : 'Agent';
      if (message.pending) {
        const typing = document.createElement('span');
        typing.className = 'typing';
        typing.append(document.createElement('span'), document.createElement('span'), document.createElement('span'));
        role.appendChild(typing);
      }
      const content = document.createElement('div');
      content.className = 'content';
      content.textContent = message.content || '';
      bubble.append(role, content);
      if (message.json) {
        const pre = document.createElement('pre');
        pre.className = 'inline-json';
        pre.textContent = JSON.stringify(message.json, null, 2);
        bubble.appendChild(pre);
      }
      if (message.meta) {
        const meta = document.createElement('div');
        meta.className = 'meta';
        meta.textContent = message.meta;
        bubble.appendChild(meta);
      }
      wrap.append(avatar, bubble);
      return wrap;
    }
    async function getJSON(url, options) {
      const res = await fetch(url, options);
      let data;
      try { data = await res.json(); } catch (err) { data = {error: await res.text()}; }
      if (!res.ok) throw new Error(data && data.error ? data.error : JSON.stringify(data));
      return data;
    }
    async function loadStatus() {
      try {
        const status = await getJSON('/api/status');
        els.sandbox.textContent = status.sandbox_url || '-';
        els.model.textContent = status.model_name || '-';
        els.steps.textContent = String(status.max_steps || '-');
        els.trace.textContent = status.trace_path || 'disabled';
        els.keyState.textContent = status.has_model_key ? 'Model key: 已配置' : 'Model key: 未配置';
      } catch (err) {
        els.sandbox.textContent = 'offline';
        els.keyState.textContent = `Status error: ${err.message}`;
      }
    }
    function buildTask(prompt) {
      const history = currentChat().messages
        .filter(item => item.role === 'user' || item.role === 'assistant')
        .slice(-8)
        .map(item => `${item.role === 'user' ? '用户' : '助手'}：${item.content}`)
        .join('\n');
      if (!history) return prompt;
      return ['下面是当前 Web UI 对话的最近上下文，请在理解上下文后完成用户最新任务。', '', history, '', `用户最新任务：${prompt}`].join('\n');
    }
    async function runAgent() {
      const prompt = els.prompt.value.trim();
      if (!prompt || busy) return;
      busy = true;
      els.send.disabled = true;
      els.toolDemo.disabled = true;
      els.prompt.value = '';
      addMessage('user', prompt);
      const pending = addMessage('assistant', '正在运行 Agent...', {pending: true});
      try {
        const data = await getJSON('/api/run', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({task: buildTask(prompt)})
        });
        updateMessage(pending.id, {pending: false, content: data.final_answer || '(没有返回 final_answer)', meta: `steps: ${data.steps}`});
      } catch (err) {
        updateMessage(pending.id, {role: 'error', pending: false, content: err.message || String(err)});
      } finally {
        busy = false;
        els.send.disabled = false;
        els.toolDemo.disabled = false;
        els.prompt.focus();
      }
    }
    async function runDemo() {
      if (busy) return;
      busy = true;
      els.send.disabled = true;
      els.toolDemo.disabled = true;
      const pending = addMessage('assistant', '正在运行工具 Demo...', {pending: true});
      try {
        const data = await getJSON('/api/demo', {method: 'POST'});
        updateMessage(pending.id, {pending: false, content: '工具 Demo 已完成。结果如下：', json: data});
      } catch (err) {
        updateMessage(pending.id, {role: 'error', pending: false, content: err.message || String(err)});
      } finally {
        busy = false;
        els.send.disabled = false;
        els.toolDemo.disabled = false;
      }
    }
    els.send.addEventListener('click', runAgent);
    els.toolDemo.addEventListener('click', runDemo);
    els.clearChat.addEventListener('click', clearCurrentChat);
    els.deleteChat.addEventListener('click', deleteCurrentChat);
    els.newChat.addEventListener('click', createChat);
    els.openSidebar.addEventListener('click', () => els.sidebar.classList.add('open'));
    els.collapseSidebar.addEventListener('click', () => els.sidebar.classList.remove('open'));
    els.prompt.addEventListener('keydown', event => {
      if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        runAgent();
      }
    });
    render();
    loadStatus();
  </script>
</body>
</html>
"""


def run_web_server(config: AgentConfig, host: str, port: int, trace_path: str | None, approval_mode: str) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/" or self.path == "/index.html":
                self._send_html(HTML)
                return
            if self.path == "/api/status":
                self._send_json(
                    {
                        "sandbox_url": config.sandbox_url,
                        "trace_path": trace_path,
                        "model_name": config.model_name,
                        "max_steps": config.max_steps,
                        "approval_mode": approval_mode,
                        "has_model_key": bool(config.model_api_key),
                    }
                )
                return
            self._send_json({"error": "not found"}, status=404)

        def do_POST(self) -> None:
            if self.path == "/api/demo":
                self._send_json(self._run_demo())
                return
            if self.path == "/api/run":
                body = self._read_json()
                task = str(body.get("task", "")).strip()
                if not task:
                    self._send_json({"error": "missing task"}, status=400)
                    return
                try:
                    sandbox = SandboxClient(config.sandbox_url)
                    tools = build_default_tools(sandbox)
                    runtime = AgentRuntime(
                        config=config,
                        tools=tools,
                        trace=TraceLogger(trace_path),
                        approval=ApprovalPolicy(approval_mode),
                    )
                    result = runtime.run(task)
                    self._send_json({"final_answer": result.final_answer, "steps": result.steps})
                except Exception as exc:
                    self._send_json({"error": str(exc)}, status=500)
                return
            self._send_json({"error": "not found"}, status=404)

        def _run_demo(self) -> dict[str, Any]:
            sandbox = SandboxClient(config.sandbox_url)
            return {
                "shell_exec": sandbox.shell_exec("pwd && ls -la | head"),
                "file_write": sandbox.file_write("/home/gem/web_demo.txt", "hello from web ui\n"),
                "file_read": sandbox.file_read("/home/gem/web_demo.txt"),
                "browser_navigate": sandbox.browser_navigate("https://example.com"),
            }

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            return json.loads(raw)

        def _send_html(self, html: str, status: int = 200) -> None:
            data = html.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
            data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args: Any) -> None:
            return

    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Web UI: http://{host}:{port}")
    server.serve_forever()
