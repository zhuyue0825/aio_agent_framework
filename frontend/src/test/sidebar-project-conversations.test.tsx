import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import Sidebar from "../Sidebar";
import type { Conversation, Project } from "../api";

const now = "2026-08-28T09:00:00Z";
const project: Project = {
  id: "project-1",
  name: "aio-project",
  workspace_root: "/workspaces/aio-project",
  owner_id: "user-1",
  created_at: now,
  updated_at: now,
};

function conversation(id: string, title: string, projectId: string | null): Conversation {
  return {
    id,
    title,
    mode: projectId ? "project" : "chat",
    model_provider: "local",
    model_id: "local:minimind-64m",
    project_id: projectId,
    created_at: now,
    updated_at: now,
    message_count: 2,
  };
}

it("groups project conversations under their project and keeps standalone chats in recent conversations", async () => {
  const selectConversation = vi.fn();
  const createProjectConversation = vi.fn();
  render(
    <Sidebar
      activePage="agent"
      mode="project"
      conversations={[
        conversation("project-conversation", "项目里的对话", project.id),
        conversation("standalone-conversation", "普通对话", null),
      ]}
      currentId="project-conversation"
      projects={[project]}
      currentProjectId={project.id}
      projectLoadingId={null}
      unavailableProjectIds={new Set()}
      onCreate={vi.fn()}
      onCreateProjectConversation={createProjectConversation}
      onDeleteConversation={vi.fn()}
      onOpenFolder={vi.fn()}
      onOpenMcpServers={vi.fn()}
      onSelectConversation={selectConversation}
      onSelectProject={vi.fn()}
    />,
  );

  const projectGroup = screen.getByRole("region", { name: "aio-project 项目" });
  const recentList = screen.getByRole("list", { name: "最近对话" });
  expect(within(projectGroup).getByRole("button", { name: "项目里的对话" })).toBeVisible();
  expect(within(recentList).getByRole("button", { name: "普通对话" })).toBeVisible();
  expect(within(recentList).queryByRole("button", { name: "项目里的对话" })).not.toBeInTheDocument();

  await userEvent.click(within(projectGroup).getByRole("button", { name: "项目里的对话" }));
  expect(selectConversation).toHaveBeenCalledWith("project-conversation");

  await userEvent.click(screen.getByRole("button", { name: "在 aio-project 中新建对话" }));
  expect(createProjectConversation).toHaveBeenCalledWith(project.id);
});

it("marks a project that is unavailable in the current deployment", () => {
  render(
    <Sidebar
      activePage="agent"
      mode="chat"
      conversations={[]}
      currentId={null}
      projects={[project]}
      currentProjectId={null}
      projectLoadingId={null}
      unavailableProjectIds={new Set([project.id])}
      onCreate={vi.fn()}
      onCreateProjectConversation={vi.fn()}
      onDeleteConversation={vi.fn()}
      onOpenFolder={vi.fn()}
      onOpenMcpServers={vi.fn()}
      onSelectConversation={vi.fn()}
      onSelectProject={vi.fn()}
    />,
  );

  expect(screen.getByText("不可用")).toBeVisible();
  expect(within(screen.getByRole("region", { name: "aio-project 项目" })).getByTitle(/当前部署不可用/)).toHaveAttribute(
    "title",
    "/workspaces/aio-project（当前部署不可用）",
  );
});
