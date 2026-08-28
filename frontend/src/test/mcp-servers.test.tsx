import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import McpServersPage from "../McpServersPage";
import { api, type McpServer, type McpServersResponse } from "../api";

const tools = [
  { name: "qq_mail_list_folders", description: "列出目录", read_only: true },
  { name: "qq_mail_list_messages", description: "列出邮件", read_only: true },
  { name: "qq_mail_search_messages", description: "搜索邮件", read_only: true },
  { name: "qq_mail_read_message", description: "读取邮件", read_only: true },
];

const emptyResponse: McpServersResponse = {
  servers: [],
  catalog: [
    {
      kind: "qq_mail",
      display_name: "QQ 邮箱",
      description: "通过内置 MCP Server 安全读取和搜索 QQ 邮件",
      transport: "builtin",
      tools,
    },
  ],
};

afterEach(() => vi.restoreAllMocks());

it("connects QQ Mail without echoing the authorization code", async () => {
  vi.spyOn(api, "listMcpServers").mockResolvedValue(emptyResponse);
  const server: McpServer = {
    id: "mcp-1",
    kind: "qq_mail",
    display_name: "QQ 邮箱",
    transport: "builtin",
    enabled: true,
    status: "connected",
    account: "12****@qq.com",
    credential_configured: true,
    tools,
    last_checked_at: new Date().toISOString(),
    last_error_code: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };
  const connect = vi.spyOn(api, "connectQqMail").mockResolvedValue({ server });

  render(<McpServersPage username="student" onLogout={() => undefined} />);
  await screen.findByText("通过内置 MCP Server 安全读取和搜索 QQ 邮件");
  await userEvent.click(screen.getByRole("button", { name: "连接 QQ 邮箱" }));
  await userEvent.type(screen.getByLabelText("QQ 邮箱地址"), "123456789@qq.com");
  const secretInput = screen.getByLabelText("邮箱授权码") as HTMLInputElement;
  expect(secretInput.type).toBe("password");
  await userEvent.type(secretInput, "qq-mail-auth-code");
  await userEvent.click(screen.getByRole("button", { name: "测试并连接" }));

  await waitFor(() => expect(connect).toHaveBeenCalledWith("123456789@qq.com", "qq-mail-auth-code"));
  expect(await screen.findByText("12****@qq.com")).toBeVisible();
  expect(screen.queryByDisplayValue("qq-mail-auth-code")).not.toBeInTheDocument();
  expect(screen.getByText(/4 个只读邮件工具/)).toBeVisible();
});
