import { Cloud, Cpu, FolderCode, FolderOpen, LogOut, MessageSquare, Send, Settings, Square } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import type { AppMode, Message, ModelOptions, Status, Workspace, MaterialSelection, Evidence, Attachment } from "./api";
import RichText from "./RichText";
import MaterialComposer from "./MaterialComposer";
import EvidencePanel from "./EvidencePanel";

type ChatProps = {
  status: Status | null;
  modelOptions: ModelOptions | null;
  modelId: string;
  hasConversation: boolean;
  mode: AppMode;
  workspace: Workspace | null;
  messages: Message[];
  busy: boolean;
  progress: string | null;
  streamingText: string;
  username: string;
  canManageModel: boolean;
  onLogout: () => void;
  onCancel: () => void;
  onOpenFolder: () => void;
  onOpenModelSettings: () => void;
  onModelChange: (modelId: string) => Promise<void>;
  conversationId?: string;
  projectId?: string;
  liveSources?: Evidence[];
  onSend: (task: string, materials?: MaterialSelection) => Promise<boolean | void>;
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
  modelOptions,
  modelId,
  hasConversation,
  mode,
  workspace,
  messages,
  busy,
  progress,
  streamingText,
  username,
  canManageModel,
  onLogout,
  onCancel,
  onOpenFolder,
  onOpenModelSettings,
  onModelChange,
  onSend, conversationId = "", projectId, liveSources = [],
}: ChatProps) {
  const [draft, setDraft] = useState("");
  const [materials,setMaterials] = useState<MaterialSelection>({attachment_ids:[],knowledge_ids:[]});
  const [materialBlocked,setMaterialBlocked] = useState(false);
  const [reset,setReset] = useState(0);
  const [source,setSource] = useState<Evidence|null>(null);
  const closeSource=useCallback(()=>setSource(null),[]);
  const selectMaterials=useCallback((value:MaterialSelection,blocked:boolean)=>{setMaterials(value);setMaterialBlocked(blocked);},[]);
  function viewAttachment(a:Attachment) {setSource({evidence_id:"",kind:a.source_kind,name:a.name,text:"",location:"文件快照",path:a.source_path,chunk_id:"s1",attachment_id:a.id});}
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages, busy, progress, streamingText]);

  async function submit() {
    const task = draft.trim();
    if (!task || busy || materialBlocked) return;
    const accepted = await onSend(task,materials);
    if(accepted !== false) {setDraft("");setReset(value=>value+1);}
  }

  const projectReady = mode === "chat" || Boolean(workspace);
  const selectedModel = modelOptions?.models.find((option) => option.id === modelId);
  const remoteRemaining = modelOptions?.deepseek_quota.remaining;
  const prompts =
    mode === "chat"
      ? ["介绍一下你自己", "用通俗的话解释什么是大语言模型", "帮我整理一个学习计划"]
      : ["先阅读项目结构并介绍主要模块", "找到项目的启动入口并解释运行流程", "检查当前项目里最值得改进的一处代码"];

  return (
    <main className="chat-shell">
      <header className="topbar">
        <div className="topbar-context">
          <label
            className="conversation-model-control"
            title={selectedModel?.unavailable_reason ?? "当前对话使用的模型"}
          >
            {selectedModel?.provider === "remote" ? <Cloud size={15} /> : <Cpu size={15} />}
            <span>当前对话</span>
            <select
              aria-label="当前对话模型"
              value={modelId}
              disabled={busy || !hasConversation}
              onChange={(event) => void onModelChange(event.target.value)}
            >
              {modelOptions && !selectedModel ? (
                <option value={modelId} disabled>
                  当前模型已不在注册表中
                </option>
              ) : null}
              {modelOptions?.models.map((option) => (
                <option key={option.id} value={option.id} disabled={!option.available}>
                  {option.display_name}
                  {option.provider === "remote" && remoteRemaining !== null && remoteRemaining !== undefined
                    ? `（今日剩余 ${remoteRemaining} 次）`
                    : ""}
                  {!option.available && option.unavailable_reason ? ` — ${option.unavailable_reason}` : ""}
                </option>
              )) ?? <option value={modelId}>正在读取模型...</option>}
            </select>
            <strong>{selectedModel?.model_name ?? status?.model_name ?? "连接中"}</strong>
          </label>
          {canManageModel ? (
            <button className="icon-button" title="管理员模型配置" disabled={busy} onClick={onOpenModelSettings}>
              <Settings size={16} />
            </button>
          ) : null}
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
                  ? "可添加附件或选择知识库，让回答有据可查。"
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
                    {message.role === "user" ? (
                      <div className="content plain-text">{message.content}</div>
                    ) : (
                      <RichText sources={Array.isArray(message.metadata?.sources)?message.metadata.sources as Evidence[]:[]} onSource={setSource}>{message.content}</RichText>
                    )}
                    {Array.isArray(message.metadata?.attachments) && <div className="message-materials">{(message.metadata.attachments as Attachment[]).map(a=><button key={a.id} onClick={()=>viewAttachment(a)}>📎 {a.name}</button>)}</div>}
                    {Array.isArray(message.metadata?.knowledge_ids) && message.metadata.knowledge_ids.length>0 && <div className="meta">已选择：中文通用检索演示库</div>}
                    {Array.isArray(message.metadata?.retrievals) && message.metadata.retrievals.length>0 && <details className="retrieval-record"><summary>知识库检索记录 · {message.metadata.retrievals.length} 次</summary>{(message.metadata.retrievals as {query:string;status:string;count:number;duration_ms:number}[]).map((r,i)=><div key={i}><strong>{r.query}</strong><small>{r.status==="completed"?`返回 ${r.count} 条资料`:"检索失败"} · {(r.duration_ms/1000).toFixed(2)} 秒（含问题向量化）</small></div>)}</details>}
                    {Array.isArray(message.metadata?.sources) && message.metadata.sources.length>0 && <div className="message-sources"><small>已查阅来源 · 点击查看原文</small>{(message.metadata.sources as Evidence[]).map(s=><button key={s.evidence_id} onClick={()=>setSource(s)}>[{s.evidence_id}] {s.name} · {s.location}{s.cited?" · 已引用":""}</button>)}</div>}
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
                {streamingText ? <RichText className="streaming-content" sources={liveSources} onSource={setSource}>{streamingText}</RichText> : null}
                {liveSources.length>0 && <div className="message-sources"><small>本次检索 / 读取的来源</small>{liveSources.map(s=><button key={s.evidence_id} onClick={()=>setSource(s)}>[{s.evidence_id}] {s.name} · {s.location}</button>)}</div>}
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

      {source && <EvidencePanel source={source} conversationId={conversationId} onClose={closeSource}/>}
      <footer className="composer-wrap">
        {conversationId && <MaterialComposer conversationId={conversationId} projectId={projectId} workspace={workspace} busy={busy} reset={reset} onChange={selectMaterials}/>}
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
            disabled={busy || materialBlocked || !draft.trim() || !projectReady}
            onClick={() => void submit()}
          >
            <Send size={18} />
            <span>发送</span>
          </button>
        </div>
        <div className="hint">
          <span>Enter 发送，Shift+Enter 换行</span>
          <span>{mode === "project" ? workspace?.root ?? "未打开项目" : "附件仅用于当前对话"}</span>
        </div>
      </footer>
    </main>
  );
}
