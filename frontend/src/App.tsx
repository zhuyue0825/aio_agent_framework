import { useEffect, useRef, useState } from "react";
import {
  api,
  hasAccessToken,
  isTerminalRun,
  setAccessToken,
  type AgentRun,
  type AppMode,
  type AuthResponse,
  type Conversation,
  type Message,
  type ModelOptions,
  type ModelProvider,
  type Project,
  type RunEvent,
  type Status,
  type User,
  type Workspace,
  type WorkspaceFile,
} from "./api";
import AuthScreen from "./AuthScreen";
import Chat from "./Chat";
import ChangeProposalPanel from "./ChangeProposalPanel";
import CodePreview from "./CodePreview";
import FolderPicker from "./FolderPicker";
import ModelSettingsDialog from "./ModelSettingsDialog";
import Sidebar from "./Sidebar";

const WORKSPACE_STORAGE_KEY = "aio-agent-workspace";

function progressText(event: RunEvent) {
  const step = typeof event.payload.step === "number" ? `第 ${event.payload.step} 步` : "";
  const tool = typeof event.payload.tool === "string" ? event.payload.tool : "工具";
  switch (event.event_type) {
    case "run.created":
      return "任务已创建";
    case "run.started":
    case "agent.request.accepted":
      return "Agent 服务已接收任务";
    case "agent.step.started":
      return `${step || "下一步"}：请求模型`;
    case "agent.model.completed":
      return `${step || "当前步骤"}：模型响应完成`;
    case "agent.tool.started":
      return `${step || "当前步骤"}：执行 ${tool}`;
    case "agent.tool.completed":
      return `${tool} 执行完成`;
    case "agent.response.ready":
      return "正在保存 Agent 回复";
    case "run.succeeded":
      return "任务完成";
    case "run.cancelled":
      return "任务已取消";
    case "run.timed_out":
      return "任务执行超时";
    case "run.failed":
      return "任务执行失败";
    default:
      return "Agent 正在处理";
  }
}

export default function App() {
  const [authReady, setAuthReady] = useState(false);
  const [user, setUser] = useState<User | null>(null);
  const [status, setStatus] = useState<Status | null>(null);
  const [modelOptions, setModelOptions] = useState<ModelOptions | null>(null);
  const [mode, setMode] = useState<AppMode>("chat");
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [currentId, setCurrentId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [project, setProject] = useState<Project | null>(null);
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [selectedFile, setSelectedFile] = useState<WorkspaceFile | null>(null);
  const [modifiedFiles, setModifiedFiles] = useState<string[]>([]);
  const [folderPickerOpen, setFolderPickerOpen] = useState(false);
  const [modelSettingsOpen, setModelSettingsOpen] = useState(false);
  const [savingFile, setSavingFile] = useState(false);
  const [activeRun, setActiveRun] = useState<AgentRun | null>(null);
  const [runProgress, setRunProgress] = useState<string | null>(null);
  const [streamingText, setStreamingText] = useState("");
  const [proposalRun, setProposalRun] = useState<AgentRun | null>(null);
  const [proposalBusy, setProposalBusy] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const runAbortRef = useRef<AbortController | null>(null);

  async function refreshModelOptions() {
    const options = await api.modelOptions();
    setModelOptions(options);
    return options;
  }

  async function refreshConversations(selectId?: string) {
    const data = await api.listConversations();
    setConversations(data.conversations);
    const preferredId = selectId ?? currentId;
    const nextId = data.conversations.some((item) => item.id === preferredId)
      ? preferredId
      : data.conversations[0]?.id ?? null;
    setCurrentId(nextId);
    return nextId;
  }

  async function loadMessages(conversationId: string | null) {
    if (!conversationId) {
      setMessages([]);
      return;
    }
    const data = await api.listMessages(conversationId);
    setMessages(data.messages);
  }

  async function openProject(path: string, switchMode = true) {
    const data = await api.openProject(path);
    setProject(data.project);
    setWorkspace(data.workspace);
    setSelectedFile(null);
    setModifiedFiles([]);
    localStorage.setItem(WORKSPACE_STORAGE_KEY, data.workspace.root);
    if (switchMode) setMode("project");
  }

  async function refreshWorkspace() {
    if (!project) return null;
    const data = await api.workspaceTree(project.id);
    setWorkspace(data.workspace);
    return data.workspace;
  }

  async function selectFile(path: string) {
    if (!project) return;
    try {
      const data = await api.workspaceFile(project.id, path);
      setSelectedFile(data.file);
    } catch (err) {
      setToast(err instanceof Error ? err.message : String(err));
    }
  }

  async function saveFile(content: string) {
    if (!project || !selectedFile) return;
    setSavingFile(true);
    setToast(null);
    try {
      const data = await api.saveWorkspaceFile(project.id, selectedFile.path, content);
      setSelectedFile(data.file);
      setModifiedFiles((current) => Array.from(new Set([...current, data.file.path])));
      await refreshWorkspace();
    } catch (err) {
      setToast(err instanceof Error ? err.message : String(err));
      throw err;
    } finally {
      setSavingFile(false);
    }
  }

  async function initializeAuthenticatedApp() {
    try {
      setStatus(await api.status());
    } catch (err) {
      setStatus(null);
      setToast(err instanceof Error ? `状态检查失败：${err.message}` : String(err));
    }
    try {
      await refreshModelOptions();
    } catch (err) {
      setModelOptions(null);
      setToast(err instanceof Error ? `模型选项读取失败：${err.message}` : String(err));
    }
    const id = await refreshConversations();
    await loadMessages(id);
    const previousWorkspace = localStorage.getItem(WORKSPACE_STORAGE_KEY);
    if (previousWorkspace) {
      try {
        await openProject(previousWorkspace, false);
      } catch {
        localStorage.removeItem(WORKSPACE_STORAGE_KEY);
      }
    }
  }

  function clearAuthenticatedState() {
    runAbortRef.current?.abort();
    runAbortRef.current = null;
    setAccessToken(null);
    setUser(null);
    setStatus(null);
    setModelOptions(null);
    setConversations([]);
    setCurrentId(null);
    setMessages([]);
    setProject(null);
    setWorkspace(null);
    setSelectedFile(null);
    setActiveRun(null);
    setRunProgress(null);
    setStreamingText("");
    setProposalRun(null);
    setModelSettingsOpen(false);
  }

  useEffect(() => {
    const expireSession = () => {
      clearAuthenticatedState();
      setToast("登录已过期，请重新登录");
      setAuthReady(true);
    };
    window.addEventListener("aio-agent-auth-expired", expireSession);
    void (async () => {
      try {
        const restored = hasAccessToken() ? await api.me() : await api.restoreSession();
        setUser(restored.user);
        await initializeAuthenticatedApp();
      } catch {
        clearAuthenticatedState();
      } finally {
        setAuthReady(true);
      }
    })();
    return () => window.removeEventListener("aio-agent-auth-expired", expireSession);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (user) void loadMessages(currentId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentId]);

  async function authenticated(session: AuthResponse) {
    setAccessToken(session.access_token);
    setUser(session.user);
    await initializeAuthenticatedApp();
  }

  async function createConversation() {
    try {
      const currentProvider = conversations.find((item) => item.id === currentId)?.model_provider ?? "local";
      const data = await api.createConversation("新对话", currentProvider);
      const id = data.conversation.id;
      await refreshConversations(id);
      await loadMessages(id);
    } catch (err) {
      setToast(err instanceof Error ? err.message : String(err));
    }
  }

  async function selectConversationModel(provider: ModelProvider) {
    if (!currentId || activeRun) return;
    try {
      const { conversation } = await api.updateConversationModel(currentId, provider);
      setConversations((current) => current.map((item) => (item.id === conversation.id ? conversation : item)));
      setToast(`当前对话已切换为 ${provider === "local" ? "MiniMind" : "DeepSeek"}`);
      await refreshModelOptions();
    } catch (err) {
      setToast(err instanceof Error ? err.message : String(err));
    }
  }

  async function deleteConversation(id: string) {
    if (activeRun?.conversation_id === id) {
      setToast("请先取消当前任务，再删除这个对话");
      return;
    }
    try {
      await api.deleteConversation(id);
      const nextId = await refreshConversations(id === currentId ? undefined : currentId ?? undefined);
      await loadMessages(nextId);
    } catch (err) {
      setToast(err instanceof Error ? err.message : String(err));
    }
  }

  async function send(task: string) {
    if (!currentId || activeRun) return;
    if (mode === "project" && (!workspace || !project)) {
      setFolderPickerOpen(true);
      return;
    }
    setToast(null);
    setRunProgress("正在创建任务");
    setStreamingText("");
    const abortController = new AbortController();
    runAbortRef.current = abortController;
    try {
      const created = await api.createRun(currentId, task, mode, project?.id);
      setActiveRun(created.run);
      await loadMessages(currentId);
      let finalRun: AgentRun;
      try {
        await api.streamRunEvents(
          created.run.id,
          (event) => {
            setRunProgress(progressText(event));
            if (event.event_type === "agent.token.delta" && typeof event.payload.delta === "string") {
              setStreamingText((current) => current + String(event.payload.delta));
            }
          },
          abortController.signal,
        );
        finalRun = (await api.getRun(created.run.id)).run;
      } catch (streamError) {
        if (streamError instanceof DOMException && streamError.name === "AbortError") {
          finalRun = (await api.getRun(created.run.id)).run;
        } else {
          setRunProgress("进度流中断，正在查询任务状态");
          finalRun = await api.waitForRun(created.run.id, abortController.signal);
        }
      }
      if (!isTerminalRun(finalRun.status)) finalRun = await api.waitForRun(finalRun.id, abortController.signal);

      await refreshConversations(currentId);
      await loadMessages(currentId);
      if (mode === "project" && project) {
        setModifiedFiles(finalRun.changed_files);
        await refreshWorkspace();
        if (finalRun.changed_files[0]) await selectFile(finalRun.changed_files[0]);
        else if (selectedFile) await selectFile(selectedFile.path);
      }
      if (finalRun.status === "FAILED" || finalRun.status === "TIMED_OUT") {
        throw new Error(finalRun.error_message || "Agent 任务执行失败");
      }
      if (finalRun.status === "CANCELLED") setToast("任务已取消");
      if (finalRun.change_status === "PROPOSED" && finalRun.proposed_changes.length) {
        setProposalRun(finalRun);
      }
    } catch (err) {
      if (!(err instanceof DOMException && err.name === "AbortError")) {
        setToast(err instanceof Error ? err.message : String(err));
        await loadMessages(currentId);
      }
    } finally {
      void refreshModelOptions().catch(() => undefined);
      runAbortRef.current = null;
      setActiveRun(null);
      setRunProgress(null);
      setStreamingText("");
    }
  }

  async function applyProposedChanges() {
    if (!proposalRun) return;
    setProposalBusy(true);
    try {
      const { run } = await api.applyRunChanges(proposalRun.id);
      setProposalRun(null);
      setModifiedFiles(run.changed_files);
      await refreshWorkspace();
      if (run.changed_files[0]) await selectFile(run.changed_files[0]);
      await loadMessages(currentId);
      setToast(`已写入 ${run.changed_files.length} 个文件`);
    } catch (err) {
      setToast(err instanceof Error ? err.message : String(err));
    } finally {
      setProposalBusy(false);
    }
  }

  async function rejectProposedChanges() {
    if (!proposalRun) return;
    setProposalBusy(true);
    try {
      await api.rejectRunChanges(proposalRun.id);
      setProposalRun(null);
      setToast("已拒绝 Agent 修改，项目文件未变化");
    } catch (err) {
      setToast(err instanceof Error ? err.message : String(err));
    } finally {
      setProposalBusy(false);
    }
  }

  async function cancelActiveRun() {
    if (!activeRun) return;
    setRunProgress("正在取消任务");
    try {
      const { run } = await api.cancelRun(activeRun.id);
      if (run.status === "CANCELLED") setToast("任务已取消");
      runAbortRef.current?.abort();
    } catch (err) {
      setToast(err instanceof Error ? err.message : String(err));
    }
  }

  async function logout() {
    if (activeRun) {
      try {
        await api.cancelRun(activeRun.id);
      } catch {
        // Logging out still clears local credentials if the cancellation request cannot complete.
      }
    }
    try {
      await api.logout();
    } catch {
      // Local logout still clears the access token if the server is unavailable.
    }
    clearAuthenticatedState();
  }

  if (!authReady) {
    return <div className="app-loading">正在恢复登录状态...</div>;
  }

  if (!user) {
    return <AuthScreen onAuthenticated={authenticated} />;
  }

  const currentConversation = conversations.find((item) => item.id === currentId) ?? null;

  return (
    <div className={`app ${mode === "project" ? "project-mode" : "chat-mode"} ${selectedFile ? "has-preview" : ""}`}>
      <Sidebar
        mode={mode}
        conversations={conversations}
        currentId={currentId}
        workspace={workspace}
        selectedPath={selectedFile?.path ?? null}
        modifiedFiles={modifiedFiles}
        onCreate={() => void createConversation()}
        onSelectConversation={setCurrentId}
        onDeleteConversation={(id) => void deleteConversation(id)}
        onOpenFolder={() => setFolderPickerOpen(true)}
        onRefreshWorkspace={() => void refreshWorkspace()}
        onSelectFile={(path) => void selectFile(path)}
      />
      <Chat
        status={status}
        modelOptions={modelOptions}
        modelProvider={currentConversation?.model_provider ?? "local"}
        hasConversation={Boolean(currentConversation)}
        mode={mode}
        workspace={workspace}
        messages={messages}
        busy={Boolean(activeRun) || Boolean(runProgress)}
        progress={runProgress}
        streamingText={streamingText}
        username={user.username}
        canManageModel={user.role === "ADMIN"}
        onLogout={() => void logout()}
        onCancel={() => void cancelActiveRun()}
        onModeChange={setMode}
        onOpenFolder={() => setFolderPickerOpen(true)}
        onOpenModelSettings={() => setModelSettingsOpen(true)}
        onModelChange={selectConversationModel}
        onSend={send}
      />
      {mode === "project" ? (
        <CodePreview
          file={selectedFile}
          workspaceName={workspace?.name ?? null}
          modified={Boolean(selectedFile && modifiedFiles.includes(selectedFile.path))}
          saving={savingFile}
          onRefresh={() => selectedFile && void selectFile(selectedFile.path)}
          onClose={() => setSelectedFile(null)}
          onSave={saveFile}
        />
      ) : null}
      <FolderPicker
        open={folderPickerOpen}
        initialPath={workspace?.root}
        onClose={() => setFolderPickerOpen(false)}
        onOpen={async (path) => {
          try {
            await openProject(path);
            setFolderPickerOpen(false);
          } catch (err) {
            setToast(err instanceof Error ? err.message : String(err));
          }
        }}
      />
      <ModelSettingsDialog
        open={modelSettingsOpen}
        onClose={() => setModelSettingsOpen(false)}
        onSaved={async (settings) => {
          setStatus(await api.status());
          await refreshModelOptions();
          setToast(
            `已保存${settings.active_provider === "local" ? "本地模型" : "远程 API"}配置：${settings.active_model_name}`,
          );
        }}
      />
      <ChangeProposalPanel
        run={proposalRun}
        busy={proposalBusy}
        onApply={() => void applyProposedChanges()}
        onReject={() => void rejectProposedChanges()}
      />
      {toast ? (
        <div className="toast" role="alert">
          <span>{toast}</span>
          <button onClick={() => setToast(null)}>关闭</button>
        </div>
      ) : null}
    </div>
  );
}
