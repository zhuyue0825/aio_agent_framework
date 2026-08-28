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
  onCreateProjectConversation: (projectId: string) => void;
  onOpenMcpServers: () => void;
  onSelectConversation: (id: string) => void;
  onDeleteConversation: (id: string) => void;
  onSelectProject: (path: string) => void;
  onOpenFolder: () => void;
};

type ConversationItemProps = {
  conversation: Conversation;
  currentId: string | null;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
  compact?: boolean;
};

function formatTime(value: string) {
  return new Date(value).toLocaleString([], {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function ConversationItem({
  conversation,
  currentId,
  onSelect,
  onDelete,
  compact = false,
}: ConversationItemProps) {
  return (
    <div
      role="listitem"
      className={`conversation-item ${compact ? "compact" : ""} ${conversation.id === currentId ? "active" : ""}`}
    >
      <button
        className="conversation-main"
        aria-label={conversation.title}
        onClick={() => onSelect(conversation.id)}
      >
        <span className="conversation-title">{conversation.title}</span>
        <span className="conversation-meta">
          {formatTime(conversation.updated_at)} · {conversation.message_count ?? 0} 条
        </span>
      </button>
      <button
        className="icon-button danger"
        aria-label={`删除对话：${conversation.title}`}
        title="删除对话"
        onClick={() => onDelete(conversation.id)}
      >
        <Trash2 size={15} />
      </button>
    </div>
  );
}

export default function Sidebar({
  activePage,
  mode,
  conversations,
  currentId,
  projects,
  currentProjectId,
  onCreate,
  onCreateProjectConversation,
  onOpenMcpServers,
  onSelectConversation,
  onDeleteConversation,
  onSelectProject,
  onOpenFolder,
}: SidebarProps) {
  const knownProjectIds = new Set(projects.map((item) => item.id));
  const recentConversations = conversations.filter(
    (conversation) => !conversation.project_id || !knownProjectIds.has(conversation.project_id),
  );

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

      <div className="sidebar-scroll-region">
        <div className="section-heading project-section-heading">
          <span>项目</span>
          <button className="icon-button" title="打开项目文件夹" onClick={onOpenFolder}>
            <Plus size={16} />
          </button>
        </div>

        <div className="sidebar-project-list">
          {projects.map((item) => {
            const projectConversations = conversations.filter((conversation) => conversation.project_id === item.id);
            const active = activePage === "agent" && item.id === currentProjectId && mode === "project";
            return (
              <section className={`sidebar-project-group ${active ? "active" : ""}`} aria-label={`${item.name} 项目`} key={item.id}>
                <div className="sidebar-project-row">
                  <button
                    className="sidebar-project-main"
                    title={item.workspace_root}
                    onClick={() => onSelectProject(item.workspace_root)}
                  >
                    <Folder size={16} />
                    <span>{item.name}</span>
                  </button>
                  <button
                    className="icon-button project-new-conversation"
                    aria-label={`在 ${item.name} 中新建对话`}
                    title="在该项目中新建对话"
                    onClick={() => onCreateProjectConversation(item.id)}
                  >
                    <Plus size={14} />
                  </button>
                </div>
                {projectConversations.length ? (
                  <div className="project-conversation-list" role="list" aria-label={`${item.name} 的对话`}>
                    {projectConversations.map((conversation) => (
                      <ConversationItem
                        compact
                        conversation={conversation}
                        currentId={currentId}
                        key={conversation.id}
                        onDelete={onDeleteConversation}
                        onSelect={onSelectConversation}
                      />
                    ))}
                  </div>
                ) : null}
              </section>
            );
          })}
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
            <div className="conversation-list" role="list" aria-label="最近对话">
              {recentConversations.map((conversation) => (
                <ConversationItem
                  conversation={conversation}
                  currentId={currentId}
                  key={conversation.id}
                  onDelete={onDeleteConversation}
                  onSelect={onSelectConversation}
                />
              ))}
              {!recentConversations.length ? (
                <span className="sidebar-conversation-empty">未关联项目的对话会显示在这里</span>
              ) : null}
            </div>
          </>
        )}
      </div>
    </aside>
  );
}
