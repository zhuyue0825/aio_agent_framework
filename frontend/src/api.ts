export type AppMode = "chat" | "project";

export type User = {
  id: string;
  username: string;
  role: "ADMIN" | "USER";
  created_at: string;
};

export type AuthResponse = {
  access_token: string;
  token_type: "Bearer";
  expires_at: string;
  user: User;
};

export type Conversation = {
  id: string;
  title: string;
  mode: AppMode;
  project_id: string | null;
  created_at: string;
  updated_at: string;
  message_count: number;
};

export type Message = {
  id: string;
  conversation_id: string;
  role: "user" | "assistant" | "error";
  content: string;
  metadata: Record<string, unknown>;
  created_at: string;
};

export type Status = {
  business_service: "UP" | "DOWN";
  agent_service: "UP" | "DOWN";
  model_provider: ModelProvider;
  model_name: string;
  model_api_base: string;
  api_key_configured: boolean;
  max_steps: number;
  supports_projects: boolean;
};

export type ModelProvider = "local" | "remote";

export type ModelSettings = {
  active_provider: ModelProvider;
  active_model_name: string;
  remote: {
    api_base: string;
    model_name: string;
    api_key_configured: boolean;
  };
  local: {
    api_base: string;
    model_name: string;
  };
};

export type ModelSettingsUpdate = {
  active_provider: ModelProvider;
  remote_api_base: string;
  remote_model_name: string;
  remote_api_key?: string;
  local_api_base: string;
  local_model_name: string;
};

export type ModelConnectionTest = {
  ok: boolean;
  provider: ModelProvider;
  model_name: string;
  response: string;
};

export type Project = {
  id: string;
  name: string;
  workspace_root: string;
  owner_id: string;
  created_at: string;
  updated_at: string;
};

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

export type RunStatus = "PENDING" | "RUNNING" | "SUCCEEDED" | "FAILED" | "CANCELLED" | "TIMED_OUT";

export type AgentRun = {
  id: string;
  conversation_id: string;
  project_id: string | null;
  status: RunStatus;
  task: string;
  mode: AppMode;
  trace_id: string;
  final_answer: string | null;
  steps: number | null;
  changed_files: string[];
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
};

export type RunEvent = {
  id: number;
  run_id: string;
  event_type: string;
  payload: Record<string, unknown>;
  created_at: string;
};

const TOKEN_STORAGE_KEY = "aio-agent-access-token";
let accessToken = localStorage.getItem(TOKEN_STORAGE_KEY);

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly code?: string,
    public readonly traceId?: string,
  ) {
    super(message);
  }
}

export function setAccessToken(token: string | null) {
  accessToken = token;
  if (token) localStorage.setItem(TOKEN_STORAGE_KEY, token);
  else localStorage.removeItem(TOKEN_STORAGE_KEY);
}

export function hasAccessToken() {
  return Boolean(accessToken);
}

function authenticationHeaders(): Record<string, string> {
  return accessToken ? { Authorization: `Bearer ${accessToken}` } : {};
}

function notifyExpiredSession(status: number) {
  if (status === 401 && accessToken) window.dispatchEvent(new Event("aio-agent-auth-expired"));
}

async function request<T>(url: string, options?: RequestInit, authenticated = true): Promise<T> {
  const response = await fetch(url, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(authenticated ? authenticationHeaders() : {}),
      ...(options?.headers || {}),
    },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    notifyExpiredSession(response.status);
    const error = data.error ?? data.detail;
    const message = typeof error === "string" ? error : error?.message;
    throw new ApiError(message || `HTTP ${response.status}`, response.status, error?.code, error?.trace_id);
  }
  return data as T;
}

export function isTerminalRun(status: RunStatus) {
  return ["SUCCEEDED", "FAILED", "CANCELLED", "TIMED_OUT"].includes(status);
}

function parseSseBlock(block: string): RunEvent | null {
  const data = block
    .split("\n")
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).trimStart())
    .join("\n");
  if (!data) return null;
  return JSON.parse(data) as RunEvent;
}

async function streamRunEvents(
  runId: string,
  onEvent: (event: RunEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(`/api/v1/runs/${runId}/events`, {
    headers: { Accept: "text/event-stream", ...authenticationHeaders() },
    signal,
  });
  if (!response.ok) {
    notifyExpiredSession(response.status);
    throw new ApiError(`SSE HTTP ${response.status}`, response.status);
  }
  if (!response.body) throw new Error("浏览器不支持流式任务进度");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value, { stream: !done }).replace(/\r\n/g, "\n");
    let separator = buffer.indexOf("\n\n");
    while (separator >= 0) {
      const event = parseSseBlock(buffer.slice(0, separator));
      buffer = buffer.slice(separator + 2);
      if (event) onEvent(event);
      separator = buffer.indexOf("\n\n");
    }
    if (done) break;
  }
}

async function waitForRun(runId: string, signal?: AbortSignal): Promise<AgentRun> {
  for (let attempt = 0; attempt < 260; attempt += 1) {
    if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
    const { run } = await api.getRun(runId);
    if (isTerminalRun(run.status)) return run;
    await new Promise<void>((resolve, reject) => {
      const timer = window.setTimeout(resolve, 750);
      signal?.addEventListener(
        "abort",
        () => {
          window.clearTimeout(timer);
          reject(new DOMException("Aborted", "AbortError"));
        },
        { once: true },
      );
    });
  }
  throw new Error("等待 Agent 任务完成超时");
}

export const api = {
  login: (username: string, password: string) =>
    request<AuthResponse>(
      "/api/v1/auth/login",
      { method: "POST", body: JSON.stringify({ username, password }) },
      false,
    ),
  register: (username: string, password: string) =>
    request<AuthResponse>(
      "/api/v1/auth/register",
      { method: "POST", body: JSON.stringify({ username, password }) },
      false,
    ),
  me: () => request<{ user: User }>("/api/v1/auth/me"),
  status: () => request<Status>("/api/v1/status"),
  modelSettings: () => request<ModelSettings>("/api/v1/model-settings"),
  updateModelSettings: (settings: ModelSettingsUpdate) =>
    request<ModelSettings>("/api/v1/model-settings", {
      method: "PUT",
      body: JSON.stringify(settings),
    }),
  testModelSettings: () =>
    request<ModelConnectionTest>("/api/v1/model-settings/test", { method: "POST", body: "{}" }),
  listConversations: () => request<{ conversations: Conversation[] }>("/api/v1/conversations"),
  createConversation: (title = "新对话") =>
    request<{ conversation: Conversation }>("/api/v1/conversations", {
      method: "POST",
      body: JSON.stringify({ title, mode: "chat" }),
    }),
  deleteConversation: (id: string) =>
    request<{ ok: true }>(`/api/v1/conversations/${id}`, { method: "DELETE" }),
  listMessages: (conversationId: string) =>
    request<{ messages: Message[] }>(`/api/v1/conversations/${conversationId}/messages`),
  createRun: (conversationId: string, task: string, mode: AppMode, projectId?: string) =>
    request<{ run: AgentRun }>(`/api/v1/conversations/${conversationId}/runs`, {
      method: "POST",
      headers: { "Idempotency-Key": `${conversationId}-${Date.now()}-${Math.random().toString(36).slice(2)}` },
      body: JSON.stringify({
        task,
        mode,
        project_id: projectId,
        approval_mode: "auto",
        max_history_messages: 8,
      }),
    }),
  getRun: (runId: string) => request<{ run: AgentRun }>(`/api/v1/runs/${runId}`),
  cancelRun: (runId: string) => request<{ run: AgentRun }>(`/api/v1/runs/${runId}`, { method: "DELETE" }),
  streamRunEvents,
  waitForRun,
  listProjects: () => request<{ projects: Project[] }>("/api/v1/projects"),
  listDirectories: (path?: string) =>
    request<DirectoryListing>(`/api/v1/workspaces/directories${path ? `?path=${encodeURIComponent(path)}` : ""}`),
  openProject: (path: string) =>
    request<{ project: Project; workspace: Workspace }>("/api/v1/projects/open", {
      method: "POST",
      body: JSON.stringify({ path }),
    }),
  workspaceTree: (projectId: string) =>
    request<{ workspace: Workspace }>(`/api/v1/projects/${projectId}/workspace/tree`),
  workspaceFile: (projectId: string, path: string) =>
    request<{ file: WorkspaceFile }>(
      `/api/v1/projects/${projectId}/workspace/file?path=${encodeURIComponent(path)}`,
    ),
  saveWorkspaceFile: (projectId: string, path: string, content: string) =>
    request<{ file: WorkspaceFile }>(`/api/v1/projects/${projectId}/workspace/file`, {
      method: "PUT",
      body: JSON.stringify({ path, content }),
    }),
};
