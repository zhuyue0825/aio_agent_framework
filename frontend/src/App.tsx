import { useEffect, useState } from "react";
import {
  api,
  type AppMode,
  type Conversation,
  type Message,
  type Status,
  type Workspace,
  type WorkspaceFile,
} from "./api";
import Chat from "./Chat";
import CodePreview from "./CodePreview";
import FolderPicker from "./FolderPicker";
import Sidebar from "./Sidebar";

const WORKSPACE_STORAGE_KEY = "aio-agent-workspace";

export default function App() {
  const [status, setStatus] = useState<Status | null>(null);
  const [mode, setMode] = useState<AppMode>("chat");
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [currentId, setCurrentId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [selectedFile, setSelectedFile] = useState<WorkspaceFile | null>(null);
  const [modifiedFiles, setModifiedFiles] = useState<string[]>([]);
  const [folderPickerOpen, setFolderPickerOpen] = useState(false);
  const [savingFile, setSavingFile] = useState(false);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

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

  async function openWorkspace(path: string, switchMode = true) {
    const data = await api.openWorkspace(path);
    setWorkspace(data.workspace);
    setSelectedFile(null);
    setModifiedFiles([]);
    localStorage.setItem(WORKSPACE_STORAGE_KEY, data.workspace.root);
    if (switchMode) setMode("project");
  }

  async function refreshWorkspace() {
    if (!workspace) return null;
    const data = await api.workspaceTree(workspace.root);
    setWorkspace(data.workspace);
    return data.workspace;
  }

  async function selectFile(path: string) {
    if (!workspace) return;
    try {
      const data = await api.workspaceFile(workspace.root, path);
      setSelectedFile(data.file);
    } catch (err) {
      setToast(err instanceof Error ? err.message : String(err));
    }
  }

  async function saveFile(content: string) {
    if (!workspace || !selectedFile) return;
    setSavingFile(true);
    setToast(null);
    try {
      const data = await api.saveWorkspaceFile(workspace.root, selectedFile.path, content);
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

  useEffect(() => {
    void (async () => {
      try {
        setStatus(await api.status());
        const id = await refreshConversations();
        await loadMessages(id);
        const previousWorkspace = localStorage.getItem(WORKSPACE_STORAGE_KEY);
        if (previousWorkspace) {
          try {
            await openWorkspace(previousWorkspace, false);
          } catch {
            localStorage.removeItem(WORKSPACE_STORAGE_KEY);
          }
        }
      } catch (err) {
        setToast(err instanceof Error ? err.message : String(err));
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    void loadMessages(currentId);
  }, [currentId]);

  async function createConversation() {
    try {
      const data = await api.createConversation();
      const id = data.conversation.id;
      await refreshConversations(id);
      await loadMessages(id);
    } catch (err) {
      setToast(err instanceof Error ? err.message : String(err));
    }
  }

  async function deleteConversation(id: string) {
    try {
      await api.deleteConversation(id);
      const nextId = await refreshConversations(id === currentId ? undefined : currentId ?? undefined);
      await loadMessages(nextId);
    } catch (err) {
      setToast(err instanceof Error ? err.message : String(err));
    }
  }

  async function send(task: string) {
    if (!currentId) return;
    if (mode === "project" && !workspace) {
      setFolderPickerOpen(true);
      return;
    }
    setBusy(true);
    setToast(null);
    try {
      const response = await api.runConversation(currentId, task, mode, workspace?.root);
      await refreshConversations(currentId);
      await loadMessages(currentId);
      if (mode === "project" && workspace) {
        const changedFiles = response.result.changed_files;
        setModifiedFiles(changedFiles);
        await refreshWorkspace();
        if (changedFiles[0]) await selectFile(changedFiles[0]);
        else if (selectedFile) await selectFile(selectedFile.path);
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setToast(message);
      await loadMessages(currentId);
    } finally {
      setBusy(false);
    }
  }

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
        mode={mode}
        workspace={workspace}
        messages={messages}
        busy={busy}
        onModeChange={setMode}
        onOpenFolder={() => setFolderPickerOpen(true)}
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
            await openWorkspace(path);
            setFolderPickerOpen(false);
          } catch (err) {
            setToast(err instanceof Error ? err.message : String(err));
          }
        }}
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
