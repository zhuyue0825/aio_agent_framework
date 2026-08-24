import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import AuthScreen from "../AuthScreen";
import ChangeProposalPanel from "../ChangeProposalPanel";
import ModelSettingsDialog from "../ModelSettingsDialog";
import { api, type AgentRun, type AuthResponse, type ModelSettings } from "../api";

const settings: ModelSettings = {
  active_provider: "remote",
  active_model_name: "deepseek-chat",
  remote: {
    api_base: "https://api.deepseek.com",
    model_name: "deepseek-chat",
    api_key_configured: true,
  },
  local: {
    api_base: "http://127.0.0.1:8998/v1",
    model_name: "minimind",
  },
};

afterEach(() => vi.restoreAllMocks());

describe("authentication and model settings", () => {
  it("hides registration and logs in without exposing a key", async () => {
    vi.spyOn(api, "authConfig").mockResolvedValue({ registration_enabled: false });
    const session = {
      access_token: "access",
      token_type: "Bearer",
      expires_at: new Date(Date.now() + 60_000).toISOString(),
      user: { id: "u1", username: "admin", role: "ADMIN", created_at: new Date().toISOString() },
    } satisfies AuthResponse;
    vi.spyOn(api, "login").mockResolvedValue(session);
    const authenticated = vi.fn(async () => undefined);

    render(<AuthScreen onAuthenticated={authenticated} />);
    await screen.findByText("公开注册已关闭，请使用部署者配置的管理员账号。");
    expect(screen.queryByRole("button", { name: /注册/ })).not.toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("用户名"), "admin");
    await userEvent.type(screen.getByLabelText("密码"), "password-1234");
    await userEvent.click(screen.getByRole("button", { name: "登录" }));
    await waitFor(() => expect(authenticated).toHaveBeenCalledWith(session));
  });

  it("switches to local model while the stored API key stays non-readable", async () => {
    vi.spyOn(api, "modelSettings").mockResolvedValue(settings);
    const update = vi.spyOn(api, "updateModelSettings").mockResolvedValue({
      ...settings,
      active_provider: "local",
      active_model_name: "minimind",
    });

    render(<ModelSettingsDialog open onClose={() => undefined} onSaved={() => undefined} />);
    await screen.findByDisplayValue("https://api.deepseek.com");
    const keyInput = screen.getByPlaceholderText("已保存；留空表示不修改") as HTMLInputElement;
    expect(keyInput.value).toBe("");
    expect(keyInput.type).toBe("password");
    await userEvent.click(screen.getByRole("button", { name: /本地模型/ }));
    await userEvent.click(screen.getByRole("button", { name: "保存配置" }));
    await waitFor(() => expect(update).toHaveBeenCalled());
    expect(update.mock.calls[0][0].active_provider).toBe("local");
    expect(update.mock.calls[0][0]).not.toHaveProperty("remote_api_key");
  });
});

it("requires an explicit click before applying an Agent diff", async () => {
  const run = {
    id: "run-1",
    change_status: "PROPOSED",
    proposed_changes: [
      { path: "src/app.ts", original_sha256: "a".repeat(64), content: "new", diff: "-old\n+new" },
    ],
  } as AgentRun;
  const apply = vi.fn();
  const reject = vi.fn();
  render(<ChangeProposalPanel run={run} busy={false} onApply={apply} onReject={reject} />);

  expect(screen.getByText("src/app.ts").parentElement?.querySelector("pre")).toHaveTextContent("-old +new");
  expect(apply).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "确认写入" }));
  expect(apply).toHaveBeenCalledOnce();
});
