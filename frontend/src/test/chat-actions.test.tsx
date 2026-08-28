import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import Chat from "../Chat";
import type { ModelOptions, Status } from "../api";

const status: Status = {
  business_service: "UP",
  agent_service: "UP",
  model_provider: "remote",
  model_name: "deepseek-chat",
  model_api_base: "https://api.deepseek.com",
  api_key_configured: true,
  max_steps: 8,
  supports_projects: true,
};

const modelOptions: ModelOptions = {
  models: [
    {
      id: "local:minimind-64m",
      provider: "local",
      display_name: "MiniMind 64M",
      model_name: "minimind",
      source: "manifest",
      available: true,
      installed: true,
      unavailable_reason: null,
      architecture: "MiniMindForCausalLM (768 x 8)",
    },
    {
      id: "remote:deepseek",
      provider: "remote",
      display_name: "DeepSeek",
      model_name: "deepseek-chat",
      source: "configured",
      available: true,
      installed: true,
      unavailable_reason: null,
      architecture: null,
    },
  ],
  deepseek_quota: {
    limit: 20,
    used: 1,
    remaining: 19,
    resets_at: new Date(Date.now() + 86_400_000).toISOString(),
    time_zone: "Asia/Shanghai",
  },
};

it("sends a chat message and exposes cancellation for an active run", async () => {
  const send = vi.fn(async () => undefined);
  const cancel = vi.fn();
  const changeModel = vi.fn(async () => undefined);
  const baseProps = {
    status,
    modelOptions,
    modelId: "local:minimind-64m",
    hasConversation: true,
    mode: "chat" as const,
    workspace: null,
    messages: [],
    progress: null,
    streamingText: "",
    username: "admin",
    canManageModel: true,
    onLogout: vi.fn(),
    onCancel: cancel,
    onOpenFolder: vi.fn(),
    onOpenModelSettings: vi.fn(),
    onModelChange: changeModel,
    onSend: send,
  };
  const view = render(<Chat {...baseProps} busy={false} />);

  await userEvent.type(screen.getByPlaceholderText("输入消息..."), "你好");
  await userEvent.click(screen.getByRole("button", { name: "发送" }));
  expect(send).toHaveBeenCalledWith("你好");

  view.rerender(<Chat {...baseProps} busy progress="第 1 步：请求模型" streamingText="正在" />);
  expect(screen.getByText("正在")).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "取消任务" }));
  expect(cancel).toHaveBeenCalledOnce();
});

it("lets a regular user choose DeepSeek for the current conversation without exposing settings", async () => {
  const changeModel = vi.fn(async () => undefined);
  render(
    <Chat
      status={status}
      modelOptions={modelOptions}
      modelId="local:minimind-64m"
      hasConversation
      mode="chat"
      workspace={null}
      messages={[]}
      busy={false}
      progress={null}
      streamingText=""
      username="regular-user"
      canManageModel={false}
      onLogout={vi.fn()}
      onCancel={vi.fn()}
      onOpenFolder={vi.fn()}
      onOpenModelSettings={vi.fn()}
      onModelChange={changeModel}
      onSend={vi.fn(async () => undefined)}
    />,
  );

  await userEvent.selectOptions(screen.getByRole("combobox", { name: "当前对话模型" }), "remote:deepseek");
  expect(changeModel).toHaveBeenCalledWith("remote:deepseek");
  expect(screen.queryByRole("button", { name: "管理员模型配置" })).not.toBeInTheDocument();
  expect(screen.queryByText(/API Key/)).not.toBeInTheDocument();
});
