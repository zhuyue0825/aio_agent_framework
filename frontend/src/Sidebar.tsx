import {
  Bell,
  Blocks,
  ChevronDown,
  Folder,
  Plus,
  Search,
  SquarePen,
  Trash2,
} from "lucide-react";
import type { AppMode, Conversation, Project } from "./api";

type SidebarProps = {
  activePage: "agent" | "mcp";
  mode: AppMode;
  conversations: Conversation[];
  currentId: string | null;
  projects: Project[];
  currentProjectId: string | null;
  onCreate: () => void;
  onOpenMcpServers: () => void;
  onSelectConversation: (id: string) => void;
  onDeleteConversation: (id: string) => void;
  onSelectProject: (path: string) => void;
  onOpenFolder: () => void;
};

function formatTime(value: string) {
  return new Date(value).toLocaleString([], {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function Sidebar({
  activePage,
  mode,
  conversations,
  currentId,
  projects,
  currentProjectId,
  onCreate,
  onOpenMcpServers,
  onSelectConversation,
  onDeleteConversation,
  onSelectProject,
  onOpenFolder,
}: SidebarProps) {
  return (
    <aside className="sidebar">
      <div className="brand codex-brand">
        <button className="brand-name" title="AIO Agent">
          <span>AIO Agent</span>
          <ChevronDown size={15} />
        </button>
        <div className="brand-utilities">
          <button className="icon-button" title="搜索（即将支持）" disabled>
            <Search size={18} />
          </button>
          <button className="icon-button" title="通知（即将支持）" disabled>
            <Bell size={18} />
          </button>
        </div>
      </div>

      <nav className="primary-navigation" aria-label="主导航">
        <button
          className={activePage === "agent" && mode === "chat" ? "active" : ""}
          onClick={onCreate}
        >
          <SquarePen size={18} />
          <span>新对话</span>
          <Plus className="nav-trailing" size={16} />
        </button>
        <button className={activePage === "mcp" ? "active" : ""} onClick={onOpenMcpServers}>
          <Blocks size={18} />
          <span>MCP Servers</span>
        </button>
      </nav>

      <div className="section-heading project-section-heading">
        <span>项目</span>
        <button className="icon-button" title="打开项目文件夹" onClick={onOpenFolder}>
          <Plus size={16} />
        </button>
      </div>

      <div className="sidebar-project-list">
        {projects.slice(0, 8).map((item) => (
          <button
            className={activePage === "agent" && item.id === currentProjectId && mode === "project" ? "active" : ""}
            key={item.id}
            title={item.workspace_root}
            onClick={() => onSelectProject(item.workspace_root)}
          >
            <Folder size={16} />
            <span>{item.name}</span>
          </button>
        ))}
        {!projects.length ? <span className="sidebar-project-empty">打开文件夹后会显示在这里</span> : null}
      </div>

      {activePage === "mcp" ? (
        <div className="sidebar-context-note">
          <Blocks size={20} />
          <strong>工具与连接器</strong>
          <span>在右侧管理 Agent 可以使用的外部服务。</span>
        </div>
      ) : (
        <>
          <div className="section-heading">
            <span>最近对话</span>
            <button className="icon-button" title="新对话" onClick={onCreate}>
              <Plus size={16} />
            </button>
          </div>
          <div className="conversation-list">
            {conversations.map((item) => (
              <div className={`conversation-item ${item.id === currentId ? "active" : ""}`} key={item.id}>
                <button className="conversation-main" onClick={() => onSelectConversation(item.id)}>
                  <span className="conversation-title">{item.title}</span>
                  <span className="conversation-meta">
                    {formatTime(item.updated_at)} · {item.message_count ?? 0} 条
                  </span>
                </button>
                <button className="icon-button danger" title="删除对话" onClick={() => onDeleteConversation(item.id)}>
                  <Trash2 size={15} />
                </button>
              </div>
            ))}
          </div>
        </>
      )}
    </aside>
  );
}
