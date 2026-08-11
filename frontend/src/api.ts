export type Conversation = {
  id: string;
  title: string;
  created_at: number;
  updated_at: number;
  message_count?: number;
};

export type Message = {
  id: string;
  conversation_id: string;
  role: "user" | "assistant" | "error";
  content: string;
  metadata: Record<string, unknown>;
  created_at: number;
};

export type Status = {
  sandbox_url: string;
  model_api_base: string;
  model_name: string;
  max_steps: number;
  has_model_key: boolean;
  trace_path: string;
  db_path: string;
  supports_projects: boolean;
};

export type AppMode = "chat" | "project";

export type WorkspaceNode = {
  name: string;
  path: string;
  type: "directory" | "file";
  modified_at: number;
  size?: number;
  children?: WorkspaceNode[];
};

export type Workspace = {
  root: string;
  name: string;
  tree: WorkspaceNode[];
  entry_count: number;
  truncated: boolean;
};

export type WorkspaceFile = {
  path: string;
  name: string;
  content: string;
  size: number;
  modified_at: number;
  language: string;
};

export type DirectoryListing = {
  path: string;
  name: string;
  parent: string | null;
  directories: Array<{ name: string; path: string }>;
};

export type RunResult = {
  final_answer: string;
  steps: number;
  changed_files: string[];
};

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options?.headers || {}),
    },
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = data.detail;
    if (typeof detail === "string") throw new Error(detail);
    if (detail?.message) throw new Error(detail.message);
    if (data.error) throw new Error(data.error);
    throw new Error(`HTTP ${res.status}`);
  }
  return data as T;
}

export const api = {
  status: () => request<Status>("/api/status"),
  listConversations: () => request<{ conversations: Conversation[] }>("/api/conversations"),
  createConversation: (title = "新对话") =>
    request<{ conversation: Conversation }>("/api/conversations", {
      method: "POST",
      body: JSON.stringify({ title }),
    }),
  deleteConversation: (id: string) =>
    request<{ ok: true }>(`/api/conversations/${id}`, {
      method: "DELETE",
    }),
  listMessages: (conversationId: string) =>
    request<{ messages: Message[] }>(`/api/conversations/${conversationId}/messages`),
  runConversation: (conversationId: string, task: string, mode: AppMode, workspacePath?: string) =>
    request<{ user_message: Message; assistant_message: Message; result: RunResult }>(
      `/api/conversations/${conversationId}/run`,
      {
        method: "POST",
        body: JSON.stringify({
          task,
          mode,
          workspace_path: workspacePath,
          approval_mode: "auto",
          max_history_messages: 8,
        }),
      },
    ),
  listDirectories: (path?: string) =>
    request<DirectoryListing>(`/api/workspace/directories${path ? `?path=${encodeURIComponent(path)}` : ""}`),
  openWorkspace: (path: string) =>
    request<{ workspace: Workspace }>("/api/workspace/open", {
      method: "POST",
      body: JSON.stringify({ path }),
    }),
  workspaceTree: (path: string) =>
    request<{ workspace: Workspace }>(`/api/workspace/tree?path=${encodeURIComponent(path)}`),
  workspaceFile: (root: string, path: string) =>
    request<{ file: WorkspaceFile }>(
      `/api/workspace/file?root=${encodeURIComponent(root)}&path=${encodeURIComponent(path)}`,
    ),
  saveWorkspaceFile: (root: string, path: string, content: string) =>
    request<{ file: WorkspaceFile }>("/api/workspace/file", {
      method: "PUT",
      body: JSON.stringify({ root, path, content }),
    }),
  toolDemo: () => request<{ result: unknown; result_json: string }>("/api/tool-demo", { method: "POST" }),
};
