import { expect, test } from "@playwright/test";

test("uses project selection as context and shows a resizable preview only for an open file", async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 });
  const now = new Date().toISOString();
  const project = {
    id: "project-1",
    name: "aio-project",
    workspace_root: "/workspaces/aio-project",
    owner_id: "user-1",
    created_at: now,
    updated_at: now,
  };
  const workspace = {
    root: project.workspace_root,
    name: project.name,
    tree: [
      {
        name: "src",
        path: "src",
        type: "directory",
        modified_at: Date.now(),
        children: [
          {
            name: "example.ts",
            path: "src/example.ts",
            type: "file",
            modified_at: Date.now(),
            size: 27,
          },
        ],
      },
    ],
    entry_count: 2,
    truncated: false,
  };

  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    if (path === "/api/v1/auth/refresh") return route.fulfill({ status: 401, json: { error: { code: "NO_SESSION" } } });
    if (path === "/api/v1/auth/config") return route.fulfill({ json: { registration_enabled: false } });
    if (path === "/api/v1/auth/login") {
      return route.fulfill({
        json: {
          access_token: "layout-test-token",
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
          model_provider: "local",
          model_name: "minimind",
          model_api_base: "http://model.test/v1",
          api_key_configured: false,
          max_steps: 8,
          supports_projects: true,
        },
      });
    }
    if (path === "/api/v1/model-options") {
      return route.fulfill({
        json: {
          models: [
            {
              id: "local:minimind-64m",
              provider: "local",
              display_name: "MiniMind 64M",
              model_name: "minimind",
              source: "manifest",
              available: true,
              installed: true,
            },
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
    if (path === "/api/v1/conversations") return route.fulfill({ json: { conversations: [] } });
    if (path === "/api/v1/projects/open") return route.fulfill({ json: { project, workspace } });
    if (path === "/api/v1/projects/project-1/workspace/file") {
      return route.fulfill({
        json: {
          file: {
            path: "src/example.ts",
            name: "example.ts",
            content: "export const answer = 42;\n",
            size: 27,
            modified_at: Date.now(),
            language: "typescript",
          },
        },
      });
    }
    if (path === "/api/v1/projects") return route.fulfill({ json: { projects: [project] } });
    return route.fulfill({ status: 404, json: { error: { code: "NOT_MOCKED", message: path } } });
  });

  await page.goto("/");
  await page.getByLabel("用户名").fill("admin");
  await page.getByLabel("密码").fill("password-1234");
  await page.getByRole("button", { name: "登录" }).click();

  await expect(page.getByRole("button", { name: "纯对话" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "项目工作" })).toHaveCount(0);

  await page.getByRole("button", { name: "aio-project" }).click();
  await expect(page.locator(".app")).toHaveClass(/project-mode/);
  await expect(page.locator(".preview-panel")).toHaveCount(0);
  await expect(page.getByRole("separator", { name: "调整代码预览宽度" })).toHaveCount(0);

  await page.getByRole("button", { name: "example.ts" }).click();
  const preview = page.locator(".preview-panel");
  const resizer = page.getByRole("separator", { name: "调整代码预览宽度" });
  await expect(preview).toBeVisible();
  await expect(resizer).toBeVisible();

  const initialWidth = await preview.evaluate((element) => element.getBoundingClientRect().width);
  const resizerBox = await resizer.boundingBox();
  expect(resizerBox).not.toBeNull();
  if (!resizerBox) throw new Error("Preview resizer has no layout box");
  await page.mouse.move(resizerBox.x + resizerBox.width / 2, resizerBox.y + resizerBox.height / 2);
  await page.mouse.down();
  await page.mouse.move(resizerBox.x - 64, resizerBox.y + resizerBox.height / 2, { steps: 4 });
  await page.mouse.up();
  const draggedWidth = await preview.evaluate((element) => element.getBoundingClientRect().width);
  expect(draggedWidth).toBeGreaterThan(initialWidth);

  await resizer.press("ArrowLeft");
  await expect.poll(() => preview.evaluate((element) => element.getBoundingClientRect().width)).toBeGreaterThan(draggedWidth);

  await page.getByRole("button", { name: "关闭预览" }).click();
  await expect(preview).toHaveCount(0);
  await expect(resizer).toHaveCount(0);
});
