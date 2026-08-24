import { expect, test } from "@playwright/test";

test("login, create a chat run, observe progress, and cancel", async ({ page }) => {
  const now = new Date().toISOString();
  let cancelled = false;
  const run = {
    id: "run-1",
    conversation_id: "conversation-1",
    project_id: null,
    status: "RUNNING",
    task: "请解释测试",
    mode: "chat",
    trace_id: "trace-e2e",
    final_answer: null,
    steps: null,
    model_provider: null,
    model_name: null,
    model_request_count: 0,
    input_tokens: null,
    output_tokens: null,
    model_latency_ms: 0,
    attempt_count: 1,
    changed_files: [],
    proposed_changes: [],
    change_status: "NONE",
    changes_applied_at: null,
    error_code: null,
    error_message: null,
    created_at: now,
    started_at: now,
    finished_at: null,
  };
  const conversation = {
    id: "conversation-1",
    title: "新对话",
    mode: "chat",
    model_provider: "local",
    project_id: null,
    created_at: now,
    updated_at: now,
    message_count: 0,
  };

  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    const method = route.request().method();
    if (path === "/api/v1/auth/refresh") return route.fulfill({ status: 401, json: { error: { code: "NO_SESSION" } } });
    if (path === "/api/v1/auth/config") return route.fulfill({ json: { registration_enabled: false } });
    if (path === "/api/v1/auth/login") {
      return route.fulfill({
        json: {
          access_token: "access-token",
          token_type: "Bearer",
          expires_at: now,
          user: { id: "user-1", username: "admin", role: "ADMIN", created_at: now },
        },
      });
    }
    if (path === "/api/v1/status") {
      return route.fulfill({
        json: {
          business_service: "UP",
          agent_service: "UP",
          model_provider: "remote",
          model_name: "deepseek-chat",
          model_api_base: "https://api.deepseek.com",
          api_key_configured: true,
          max_steps: 8,
          supports_projects: true,
        },
      });
    }
    if (path === "/api/v1/model-options") {
      return route.fulfill({
        json: {
          models: [
            { provider: "local", display_name: "MiniMind", model_name: "minimind", available: true },
            { provider: "remote", display_name: "DeepSeek", model_name: "deepseek-chat", available: true },
          ],
          deepseek_quota: {
            limit: 20,
            used: 0,
            remaining: 20,
            resets_at: now,
            time_zone: "Asia/Shanghai",
          },
        },
      });
    }
    if (path === "/api/v1/conversations") return route.fulfill({ json: { conversations: [conversation] } });
    if (path.endsWith("/messages")) return route.fulfill({ json: { messages: [] } });
    if (path.endsWith("/runs") && method === "POST") return route.fulfill({ status: 202, json: { run } });
    if (path.endsWith("/events")) {
      return route.fulfill({
        contentType: "text/event-stream",
        body: `id: 1\nevent: agent.step.started\ndata: ${JSON.stringify({
          id: 1,
          event_type: "agent.step.started",
          payload: { step: 1 },
          created_at: now,
        })}\n\n`,
      });
    }
    if (path === "/api/v1/runs/run-1" && method === "DELETE") {
      cancelled = true;
      return route.fulfill({ json: { run: { ...run, status: "CANCELLED", finished_at: now } } });
    }
    if (path === "/api/v1/runs/run-1") {
      return route.fulfill({ json: { run: { ...run, status: cancelled ? "CANCELLED" : "RUNNING" } } });
    }
    if (path === "/api/v1/projects") return route.fulfill({ json: { projects: [] } });
    return route.fulfill({ status: 404, json: { error: { code: "NOT_MOCKED", message: path } } });
  });

  await page.goto("/");
  await expect(page.getByText("公开注册已关闭，请使用部署者配置的管理员账号。")).toBeVisible();
  await page.getByLabel("用户名").fill("admin");
  await page.getByLabel("密码").fill("password-1234");
  await page.getByRole("button", { name: "登录" }).click();
  await expect(page.getByText("开始一段对话")).toBeVisible();
  await page.getByPlaceholder("输入消息...").fill("请解释测试");
  await page.getByRole("button", { name: "发送" }).click();
  await expect(page.getByText("第 1 步：请求模型")).toBeVisible();
  await expect(page.getByRole("button", { name: "取消任务" })).toBeVisible();
  await page.getByRole("button", { name: "取消任务" }).click();
  await expect(page.getByText("任务已取消")).toBeVisible();
});
