import { useEffect, useRef, useState, type CSSProperties, type KeyboardEvent, type PointerEvent as ReactPointerEvent } from "react";
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
import McpServersPage from "./McpServersPage";
import Sidebar from "./Sidebar";

const WORKSPACE_STORAGE_KEY = "aio-agent-workspace";
const PREVIEW_WIDTH_STORAGE_KEY = "aio-agent-preview-width";
const DEFAULT_PREVIEW_WIDTH = 560;
const MIN_PREVIEW_WIDTH = 320;
const MAX_PREVIEW_WIDTH = 960;
const MIN_CHAT_WIDTH = 440;
const PREVIEW_RESIZER_WIDTH = 8;

function initialPreviewWidth() {
  const stored = Number(window.localStorage.getItem(PREVIEW_WIDTH_STORAGE_KEY));
  return Number.isFinite(stored) && stored >= MIN_PREVIEW_WIDTH ? stored : DEFAULT_PREVIEW_WIDTH;
}

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
  const [activePage, setActivePage] = useState<"agent" | "mcp">("agent");
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [currentId, setCurrentId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [project, setProject] = useState<Project | null>(null);
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [projectLoadingId, setProjectLoadingId] = useState<string | null>(null);
  const [unavailableProjectIds, setUnavailableProjectIds] = useState<Set<string>>(() => new Set());
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
  const [previewWidth, setPreviewWidth] = useState(initialPreviewWidth);
  const appRef = useRef<HTMLDivElement | null>(null);
  const runAbortRef = useRef<AbortController | null>(null);
  const previewResizeCleanupRef = useRef<(() => void) | null>(null);
  const workspaceCacheRef = useRef<Map<string, Workspace>>(new Map());
  const projectSelectionRequestRef = useRef(0);

  function previewWidthLimit() {
    const appWidth = appRef.current?.getBoundingClientRect().width ?? window.innerWidth;
    const sidebarWidth = appRef.current?.querySelector<HTMLElement>(".sidebar")?.getBoundingClientRect().width ?? 280;
    return Math.max(MIN_PREVIEW_WIDTH, Math.min(MAX_PREVIEW_WIDTH, appWidth - sidebarWidth - MIN_CHAT_WIDTH - PREVIEW_RESIZER_WIDTH));
  }

  function resizePreview(width: number) {
    const nextWidth = Math.round(Math.min(previewWidthLimit(), Math.max(MIN_PREVIEW_WIDTH, width)));
    setPreviewWidth(nextWidth);
    window.localStorage.setItem(PREVIEW_WIDTH_STORAGE_KEY, String(nextWidth));
  }

  function startPreviewResize(event: ReactPointerEvent<HTMLDivElement>) {
    if (event.button !== 0) return;
    event.preventDefault();
    previewResizeCleanupRef.current?.();

    const startX = event.clientX;
    const previewPanel = event.currentTarget.nextElementSibling as HTMLElement | null;
    const startWidth = previewPanel?.getBoundingClientRect().width ?? previewWidth;

    const handlePointerMove = (moveEvent: PointerEvent) => {
      resizePreview(startWidth + startX - moveEvent.clientX);
    };
    const stopResize = () => {
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", stopResize);
      window.removeEventListener("pointercancel", stopResize);
      document.body.classList.remove("preview-resizing");
      previewResizeCleanupRef.current = null;
    };

    document.body.classList.add("preview-resizing");
    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", stopResize);
    window.addEventListener("pointercancel", stopResize);
    previewResizeCleanupRef.current = stopResize;
  }

  function handlePreviewResizeKey(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    resizePreview(previewWidth + (event.key === "ArrowLeft" ? 32 : -32));
  }

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

  function rememberWorkspace(projectId: string, nextWorkspace: Workspace) {
    workspaceCacheRef.current.set(projectId, nextWorkspace);
  }

  function clearProjectUnavailable(projectId: string) {
    setUnavailableProjectIds((current) => {
      if (!current.has(projectId)) return current;
      const next = new Set(current);
      next.delete(projectId);
      return next;
    });
  }

  function markProjectUnavailable(projectId: string) {
    setUnavailableProjectIds((current) => {
      if (current.has(projectId)) return current;
      const next = new Set(current);
      next.add(projectId);
      return next;
    });
  }

  async function openProject(path: string, switchMode = true) {
    const requestId = ++projectSelectionRequestRef.current;
    setProjectLoadingId(null);
    const data = await api.openProject(path);
    if (requestId !== projectSelectionRequestRef.current) return false;
    rememberWorkspace(data.project.id, data.workspace);
    setProject(data.project);
    setWorkspace(data.workspace);
    clearProjectUnavailable(data.project.id);
    setSelectedFile(null);
    setModifiedFiles([]);
    localStorage.setItem(WORKSPACE_STORAGE_KEY, data.workspace.root);
    setProjects((current) => [data.project, ...current.filter((item) => item.id !== data.project.id)]);
    if (switchMode) {
      setActivePage("agent");
      setMode("project");
    }
    return true;
  }

  async function selectExistingProject(targetProject: Project, switchMode = true) {
    const requestId = ++projectSelectionRequestRef.current;
    const previousProject = project;
    const previousWorkspace = workspace;
    const cachedWorkspace = workspaceCacheRef.current.get(targetProject.id) ?? null;

    setActivePage("agent");
    if (switchMode) setMode("project");
    setProject(targetProject);
    setWorkspace(cachedWorkspace);
    setSelectedFile(null);
    setModifiedFiles([]);
    setProjectLoadingId(targetProject.id);

    try {
      const data = await api.workspaceTree(targetProject.id);
      if (requestId !== projectSelectionRequestRef.current) return false;
      rememberWorkspace(targetProject.id, data.workspace);
      setWorkspace(data.workspace);
      clearProjectUnavailable(targetProject.id);
      localStorage.setItem(WORKSPACE_STORAGE_KEY, data.workspace.root);
      return true;
    } catch (err) {
      if (requestId !== projectSelectionRequestRef.current) return false;
      markProjectUnavailable(targetProject.id);
      setProject(previousProject);
      setWorkspace(previousWorkspace);
      const reason = err instanceof Error ? err.message : String(err);
      throw new Error(
        `项目“${targetProject.name}”的目录在当前部署中不可用，可能是旧开发模式留下的记录。请从 /workspaces 重新打开有效文件夹。${reason ? ` ${reason}` : ""}`,
      );
    } finally {
      if (requestId === projectSelectionRequestRef.current) setProjectLoadingId(null);
    }
  }

  async function refreshProjects() {
    const data = await api.listProjects();
    setProjects(data.projects);
    return data.projects;
  }

  async function refreshWorkspace() {
    if (!project) return null;
    const data = await api.workspaceTree(project.id);
    rememberWorkspace(project.id, data.workspace);
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
    const loadedProjects = await refreshProjects();
    const previousWorkspace = localStorage.getItem(WORKSPACE_STORAGE_KEY);
    if (previousWorkspace) {
      try {
        const existingProject = loadedProjects.find((item) => item.workspace_root === previousWorkspace);
        if (existingProject) await selectExistingProject(existingProject, false);
        else await openProject(previousWorkspace, false);
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
    setProjects([]);
    setProject(null);
    setWorkspace(null);
    setProjectLoadingId(null);
    setUnavailableProjectIds(new Set());
    workspaceCacheRef.current.clear();
    projectSelectionRequestRef.current += 1;
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
    const keepPreviewInsideViewport = () => {
      setPreviewWidth((currentWidth) => {
        const nextWidth = Math.round(Math.min(previewWidthLimit(), Math.max(MIN_PREVIEW_WIDTH, currentWidth)));
        window.localStorage.setItem(PREVIEW_WIDTH_STORAGE_KEY, String(nextWidth));
        return nextWidth;
      });
    };
    keepPreviewInsideViewport();
    window.addEventListener("resize", keepPreviewInsideViewport);
    return () => {
      window.removeEventListener("resize", keepPreviewInsideViewport);
      previewResizeCleanupRef.current?.();
    };
    // Layout refs remain stable; the resize callback reads their current dimensions.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (user) void loadMessages(currentId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentId]);

  useEffect(() => {
    if (!user) return undefined;
    const timer = window.setInterval(() => {
      void api.modelOptions().then(setModelOptions).catch(() => undefined);
    }, 30_000);
    return () => window.clearInterval(timer);
  }, [user]);

  async function authenticated(session: AuthResponse) {
    setAccessToken(session.access_token);
    setUser(session.user);
    await initializeAuthenticatedApp();
  }

  async function createConversation(projectId?: string) {
    setActivePage("agent");
    try {
      const targetProject = projectId ? projects.find((item) => item.id === projectId) : null;
      if (projectId && !targetProject) {
        setToast("这个项目已不可用，请刷新项目列表后重试");
        return;
      }
      if (targetProject && targetProject.id !== project?.id) {
        const selected = await selectExistingProject(targetProject, false);
        if (!selected) return;
      }
      setMode(targetProject ? "project" : "chat");
      const currentModelId = conversations.find((item) => item.id === currentId)?.model_id
        ?? modelOptions?.models.find((item) => item.available)?.id
        ?? "local:minimind-64m";
      const data = await api.createConversation("新对话", currentModelId, targetProject?.id);
      const id = data.conversation.id;
      await refreshConversations(id);
      await loadMessages(id);
    } catch (err) {
      setToast(err instanceof Error ? err.message : String(err));
    }
  }

  async function selectConversation(id: string) {
    const conversation = conversations.find((item) => item.id === id);
    setActivePage("agent");
    setCurrentId(id);
    setSelectedFile(null);
    if (!conversation) return;

    setMode(conversation.mode);
    if (conversation.mode !== "project" || !conversation.project_id || conversation.project_id === project?.id) return;

    let targetProject = projects.find((item) => item.id === conversation.project_id);
    if (!targetProject) {
      const refreshedProjects = await refreshProjects();
      targetProject = refreshedProjects.find((item) => item.id === conversation.project_id);
    }
    if (!targetProject) {
      setToast("这个对话关联的项目已不可用，请重新打开项目文件夹");
      return;
    }
    try {
      await selectExistingProject(targetProject, false);
    } catch (err) {
      setToast(err instanceof Error ? err.message : String(err));
    }
  }

  async function selectConversationModel(modelId: string) {
    if (!currentId || activeRun) return;
    try {
      const { conversation } = await api.updateConversationModel(currentId, modelId);
      setConversations((current) => current.map((item) => (item.id === conversation.id ? conversation : item)));
      const displayName = modelOptions?.models.find((item) => item.id === modelId)?.display_name ?? modelId;
      setToast(`当前对话已切换为 ${displayName}`);
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
    <div
      ref={appRef}
      className={`app ${activePage === "mcp" ? "mcp-mode" : mode === "project" ? "project-mode" : "chat-mode"} ${mode === "project" && selectedFile ? "has-preview" : ""}`}
      style={{ "--preview-width": `${previewWidth}px` } as CSSProperties}
    >
      <Sidebar
        activePage={activePage}
        mode={mode}
        conversations={conversations}
        currentId={currentId}
        projects={projects}
        currentProjectId={project?.id ?? null}
        projectLoadingId={projectLoadingId}
        unavailableProjectIds={unavailableProjectIds}
        onCreate={() => void createConversation()}
        onCreateProjectConversation={(projectId) => void createConversation(projectId)}
        onOpenMcpServers={() => setActivePage("mcp")}
        onSelectConversation={(id) => void selectConversation(id)}
        onDeleteConversation={(id) => void deleteConversation(id)}
        onSelectProject={(targetProject) => {
          void selectExistingProject(targetProject).catch((err) => {
            setToast(err instanceof Error ? err.message : String(err));
          });
        }}
        onOpenFolder={() => setFolderPickerOpen(true)}
      />
      {activePage === "mcp" ? (
        <McpServersPage username={user.username} onLogout={() => void logout()} />
      ) : (
        <>
          <Chat
            status={status}
            modelOptions={modelOptions}
            modelId={currentConversation?.model_id ?? "local:minimind-64m"}
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
            onOpenFolder={() => setFolderPickerOpen(true)}
            onOpenModelSettings={() => setModelSettingsOpen(true)}
            onModelChange={selectConversationModel}
            onSend={send}
          />
          {mode === "project" && selectedFile ? (
            <>
              <div
                className="preview-resizer"
                role="separator"
                aria-label="调整代码预览宽度"
                aria-orientation="vertical"
                aria-valuemin={MIN_PREVIEW_WIDTH}
                aria-valuemax={MAX_PREVIEW_WIDTH}
                aria-valuenow={previewWidth}
                tabIndex={0}
                title="拖动调整代码预览宽度，双击恢复默认宽度"
                onDoubleClick={() => resizePreview(DEFAULT_PREVIEW_WIDTH)}
                onKeyDown={handlePreviewResizeKey}
                onPointerDown={startPreviewResize}
              >
                <span />
              </div>
              <CodePreview
                file={selectedFile}
                modified={modifiedFiles.includes(selectedFile.path)}
                saving={savingFile}
                onRefresh={() => void selectFile(selectedFile.path)}
                onClose={() => setSelectedFile(null)}
                onSave={saveFile}
              />
            </>
          ) : null}
        </>
      )}
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
