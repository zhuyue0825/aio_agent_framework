import { Cloud, Cpu, FolderCode, FolderOpen, LogOut, MessageSquare, Send, Settings, Square } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { AppMode, Message, Status, Workspace } from "./api";

type ChatProps = {
  status: Status | null;
  mode: AppMode;
  workspace: Workspace | null;
  messages: Message[];
  busy: boolean;
  progress: string | null;
  username: string;
  canManageModel: boolean;
  onLogout: () => void;
  onCancel: () => void;
  onModeChange: (mode: AppMode) => void;
  onOpenFolder: () => void;
  onOpenModelSettings: () => void;
  onSend: (task: string) => Promise<void>;
};

function roleLabel(role: Message["role"]) {
  if (role === "user") return "你";
  if (role === "error") return "错误";
  return "Agent";
}

function avatar(role: Message["role"]) {
  if (role === "user") return "你";
  if (role === "error") return "!";
  return "AI";
}

export default function Chat({
  status,
  mode,
  workspace,
  messages,
  busy,
  progress,
  username,
  canManageModel,
  onLogout,
  onCancel,
  onModeChange,
  onOpenFolder,
  onOpenModelSettings,
  onSend,
}: ChatProps) {
  const [draft, setDraft] = useState("");
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages, busy]);

  async function submit() {
    const task = draft.trim();
    if (!task || busy) return;
    setDraft("");
    await onSend(task);
  }

  const projectReady = mode === "chat" || Boolean(workspace);
  const prompts =
    mode === "chat"
      ? ["介绍一下你自己", "用通俗的话解释什么是大语言模型", "帮我整理一个学习计划"]
      : ["先阅读项目结构并介绍主要模块", "找到项目的启动入口并解释运行流程", "检查当前项目里最值得改进的一处代码"];

  return (
    <main className="chat-shell">
      <header className="topbar">
        <div className="mode-control" aria-label="工作模式">
          <button disabled={busy} className={mode === "chat" ? "active" : ""} onClick={() => onModeChange("chat")}>
            <MessageSquare size={16} />
            纯对话
          </button>
          <button disabled={busy} className={mode === "project" ? "active" : ""} onClick={() => onModeChange("project")}>
            <FolderCode size={16} />
            项目工作
          </button>
        </div>
        <div className="topbar-context">
          {canManageModel ? (
            <button
              className="model-switch-button"
              title="切换本地模型或远程 API"
              disabled={busy}
              onClick={onOpenModelSettings}
            >
              {status?.model_provider === "local" ? <Cpu size={15} /> : <Cloud size={15} />}
              <span>{status?.model_provider === "local" ? "本地" : "API"}</span>
              <strong>{status?.model_name ?? "连接中"}</strong>
              <Settings size={14} />
            </button>
          ) : (
            <span className="context-label">
              {status?.model_provider === "local" ? <Cpu size={15} /> : <Cloud size={15} />}
              <strong>{status?.model_name ?? "连接中"}</strong>
            </span>
          )}
          <div className="topbar-service-context">
            {mode === "project" ? (
              workspace ? (
                <span className="context-label" title={workspace.root}>
                  <FolderOpen size={15} />
                  {workspace.name}
                </span>
              ) : (
                <button className="open-folder-inline" onClick={onOpenFolder}>
                  <FolderOpen size={16} />
                  打开文件夹
                </button>
              )
            ) : null}
          </div>
          <span className="signed-in-user" title={`当前用户：${username}`}>{username}</span>
          <button className="icon-button" title="退出登录" onClick={onLogout}>
            <LogOut size={16} />
          </button>
        </div>
      </header>

      <section className="messages" ref={scrollRef}>
        <div className="message-stack">
          {messages.length === 0 ? (
            <div className="empty">
              <div className="empty-icon">{mode === "chat" ? <MessageSquare /> : <FolderCode />}</div>
              <h1>{mode === "chat" ? "开始一段对话" : workspace ? `在 ${workspace.name} 中工作` : "打开一个项目文件夹"}</h1>
              <p>
                {mode === "chat"
                  ? "这个模式只和模型聊天，不会读取或修改本地文件。"
                  : workspace
                    ? "Agent 可以读取和修改这个目录中的文本文件，修改结果会显示在右侧。"
                    : "选择文件夹后，可以让 Agent 阅读项目、修改代码，并在右侧预览文件。"}
              </p>
              {!projectReady ? (
                <button className="primary empty-action" onClick={onOpenFolder}>
                  <FolderOpen size={17} />
                  打开文件夹
                </button>
              ) : (
                <div className="prompt-grid">
                  {prompts.map((text) => (
                    <button key={text} onClick={() => setDraft(text)}>
                      {text}
                    </button>
                  ))}
                </div>
              )}
            </div>
          ) : (
            messages.map((message) => {
              const changedFiles = Array.isArray(message.metadata?.changed_files)
                ? (message.metadata.changed_files as string[])
                : [];
              return (
                <article className={`message ${message.role}`} key={message.id}>
                  <div className="avatar">{avatar(message.role)}</div>
                  <div className="bubble">
                    <div className="role">{roleLabel(message.role)}</div>
                    <div className="content">{message.content}</div>
                    {changedFiles.length ? (
                      <div className="changed-summary">已修改 {changedFiles.join("、")}</div>
                    ) : null}
                    {typeof message.metadata?.steps === "number" ? (
                      <div className="meta">steps: {String(message.metadata.steps)}</div>
                    ) : null}
                  </div>
                </article>
              );
            })
          )}

          {busy ? (
            <article className="message assistant">
              <div className="avatar">AI</div>
              <div className="bubble">
                <div className="role">{progress ?? (mode === "project" ? "正在处理项目" : "正在回复")}</div>
                <div className="run-progress-row">
                  <div className="typing">
                    <span />
                    <span />
                    <span />
                  </div>
                  <button className="cancel-run" onClick={onCancel}>
                    <Square size={13} />
                    取消任务
                  </button>
                </div>
              </div>
            </article>
          ) : null}
        </div>
      </section>

      <footer className="composer-wrap">
        <div className="composer">
          <textarea
            value={draft}
            disabled={!projectReady || busy}
            placeholder={
              !projectReady
                ? "请先打开项目文件夹"
                : mode === "project"
                  ? `让 Agent 在 ${workspace?.name} 中完成任务...`
                  : "输入消息..."
            }
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void submit();
              }
            }}
          />
          <button
            className="primary send-button"
            title="发送"
            disabled={busy || !draft.trim() || !projectReady}
            onClick={() => void submit()}
          >
            <Send size={18} />
            <span>发送</span>
          </button>
        </div>
        <div className="hint">
          <span>Enter 发送，Shift+Enter 换行</span>
          <span>{mode === "project" ? workspace?.root ?? "未打开项目" : "纯对话不会操作文件"}</span>
        </div>
      </footer>
    </main>
  );
}
