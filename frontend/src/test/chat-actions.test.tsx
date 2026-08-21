import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import Chat from "../Chat";
import type { Status } from "../api";

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

it("sends a chat message and exposes cancellation for an active run", async () => {
  const send = vi.fn(async () => undefined);
  const cancel = vi.fn();
  const baseProps = {
    status,
    mode: "chat" as const,
    workspace: null,
    messages: [],
    progress: null,
    streamingText: "",
    username: "admin",
    canManageModel: true,
    onLogout: vi.fn(),
    onCancel: cancel,
    onModeChange: vi.fn(),
    onOpenFolder: vi.fn(),
    onOpenModelSettings: vi.fn(),
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
