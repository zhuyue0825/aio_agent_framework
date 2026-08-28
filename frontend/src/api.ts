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

export type AuthConfig = {
  registration_enabled: boolean;
};

export type Conversation = {
  id: string;
  title: string;
  mode: AppMode;
  model_provider: ModelProvider;
  model_id: string;
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

export type ModelOption = {
  id: string;
  provider: ModelProvider;
  display_name: string;
  model_name: string;
  source: "configured" | "manifest" | "runtime" | "scan" | string;
  available: boolean;
  installed: boolean;
  unavailable_reason: string | null;
  architecture: string | null;
};

export type ModelOptions = {
  models: ModelOption[];
  deepseek_quota: {
    limit: number;
    used: number;
    remaining: number | null;
    resets_at: string;
    time_zone: string;
  };
};

export type McpTool = {
  name: string;
  description: string;
  read_only: boolean;
};

export type McpServer = {
  id: string;
  kind: "qq_mail" | string;
  display_name: string;
  transport: "builtin" | "streamable_http" | string;
  enabled: boolean;
  status: "connected" | "error" | string;
  account: string;
  credential_configured: boolean;
  tools: McpTool[];
  last_checked_at: string | null;
  last_error_code: string | null;
  created_at: string;
  updated_at: string;
};

export type McpCatalogItem = {
  kind: string;
  display_name: string;
  description: string;
  transport: string;
  tools: McpTool[];
};

export type McpServersResponse = {
  servers: McpServer[];
  catalog: McpCatalogItem[];
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
  model_provider: string | null;
  model_id: string;
  model_name: string | null;
  model_request_count: number;
  input_tokens: number | null;
  output_tokens: number | null;
  model_latency_ms: number;
  attempt_count: number;
  changed_files: string[];
  proposed_changes: Array<{
    path: string;
    original_sha256: string;
    content: string;
    diff: string;
  }>;
  change_status: "NONE" | "PROPOSED" | "APPLYING" | "APPLIED" | "APPLY_FAILED" | "REJECTED";
  changes_applied_at: string | null;
  change_apply_started_at: string | null;
  change_error_message: string | null;
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

export type ConversationPage = {
  conversations: Conversation[];
  page: number;
  size: number;
  total: number;
  has_more: boolean;
};

export type MessagePage = {
  messages: Message[];
  page: number;
  size: number;
  has_more: boolean;
};

let accessToken: string | null = null;
let refreshPromise: Promise<AuthResponse> | null = null;

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly code?: string,
    public readonly traceId?: string,
  ) {
    super(traceId ? `${message}（trace_id: ${traceId}）` : message);
  }
}

export function setAccessToken(token: string | null) {
  accessToken = token;
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

async function refreshAccessToken(): Promise<AuthResponse> {
  if (!refreshPromise) {
    refreshPromise = fetch("/api/v1/auth/refresh", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    })
      .then(async (response) => {
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new ApiError("登录会话已过期", response.status, data.error?.code ?? data.detail?.code);
        const session = data as AuthResponse;
        setAccessToken(session.access_token);
        return session;
      })
      .finally(() => {
        refreshPromise = null;
      });
  }
  return refreshPromise;
}

async function request<T>(url: string, options?: RequestInit, authenticated = true, retry = true): Promise<T> {
  const response = await fetch(url, {
    ...options,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(authenticated ? authenticationHeaders() : {}),
      ...(options?.headers || {}),
    },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401 && authenticated && retry && !url.endsWith("/auth/logout")) {
      try {
        await refreshAccessToken();
        return request<T>(url, options, authenticated, false);
      } catch {
        notifyExpiredSession(response.status);
      }
    }
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
  let lastEventId = 0;
  let lastError: unknown = null;
  for (let attempt = 0; attempt < 3; attempt += 1) {
    try {
      const response = await fetch(`/api/v1/runs/${runId}/events`, {
        headers: {
          Accept: "text/event-stream",
          ...authenticationHeaders(),
          ...(lastEventId ? { "Last-Event-ID": String(lastEventId) } : {}),
        },
        credentials: "include",
        signal,
      });
      if (response.status === 401 && attempt === 0) {
        await refreshAccessToken();
        continue;
      }
      if (!response.ok) {
        notifyExpiredSession(response.status);
        const traceId = response.headers.get("X-Trace-Id") ?? undefined;
        throw new ApiError(`SSE HTTP ${response.status}`, response.status, undefined, traceId);
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
          if (event) {
            lastEventId = Math.max(lastEventId, event.id);
            onEvent(event);
          }
          separator = buffer.indexOf("\n\n");
        }
        if (done) return;
      }
    } catch (error) {
      if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
      lastError = error;
      await new Promise((resolve) => window.setTimeout(resolve, 250 * (attempt + 1)));
    }
  }
  throw lastError instanceof Error ? lastError : new Error("任务进度流重连失败");
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
  authConfig: () => request<AuthConfig>("/api/v1/auth/config", undefined, false),
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
  restoreSession: refreshAccessToken,
  logout: () => request<{ ok: true }>("/api/v1/auth/logout", { method: "POST", body: "{}" }, true, false),
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
  modelOptions: () => request<ModelOptions>("/api/v1/model-options"),
  listMcpServers: () => request<McpServersResponse>("/api/v1/mcp/servers"),
  connectQqMail: (email: string, authorizationCode: string) =>
    request<{ server: McpServer }>("/api/v1/mcp/servers/qq-mail", {
      method: "PUT",
      body: JSON.stringify({ email, authorization_code: authorizationCode }),
    }),
  testMcpServer: (id: string) =>
    request<{ server: McpServer }>(`/api/v1/mcp/servers/${id}/test`, { method: "POST", body: "{}" }),
  setMcpServerEnabled: (id: string, enabled: boolean) =>
    request<{ server: McpServer }>(`/api/v1/mcp/servers/${id}/enabled`, {
      method: "PUT",
      body: JSON.stringify({ enabled }),
    }),
  deleteMcpServer: (id: string) =>
    request<{ ok: true }>(`/api/v1/mcp/servers/${id}`, { method: "DELETE" }),
  listConversations: (page = 0, size = 50) =>
    request<ConversationPage>(`/api/v1/conversations?page=${page}&size=${size}`),
  createConversation: (title = "新对话", modelId = "local:minimind-64m", projectId?: string) =>
    request<{ conversation: Conversation }>("/api/v1/conversations", {
      method: "POST",
      body: JSON.stringify({
        title,
        mode: projectId ? "project" : "chat",
        model_id: modelId,
        project_id: projectId ?? null,
      }),
    }),
  updateConversationModel: (id: string, modelId: string) =>
    request<{ conversation: Conversation }>(`/api/v1/conversations/${id}/model`, {
      method: "PUT",
      body: JSON.stringify({ model_id: modelId }),
    }),
  deleteConversation: (id: string) =>
    request<{ ok: true }>(`/api/v1/conversations/${id}`, { method: "DELETE" }),
  listMessages: (conversationId: string, page = 0, size = 100) =>
    request<MessagePage>(`/api/v1/conversations/${conversationId}/messages?page=${page}&size=${size}`),
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
  listRunEvents: (runId: string, after = 0, size = 100) =>
    request<{ events: RunEvent[]; has_more: boolean; next_after: number }>(
      `/api/v1/runs/${runId}/event-history?after=${after}&size=${size}`,
    ),
  cancelRun: (runId: string) => request<{ run: AgentRun }>(`/api/v1/runs/${runId}`, { method: "DELETE" }),
  applyRunChanges: (runId: string) =>
    request<{ run: AgentRun }>(`/api/v1/runs/${runId}/changes/apply`, { method: "POST", body: "{}" }),
  rejectRunChanges: (runId: string) =>
    request<{ run: AgentRun }>(`/api/v1/runs/${runId}/changes/reject`, { method: "POST", body: "{}" }),
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
