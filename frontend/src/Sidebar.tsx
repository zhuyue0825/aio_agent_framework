import {
  Bell,
  Blocks,
  ChevronDown,
  ChevronRight,
  File,
  Folder,
  FolderOpen,
  Plus,
  RefreshCw,
  Search,
  SquarePen,
  Trash2,
} from "lucide-react";
import { useEffect, useState } from "react";
import type { AppMode, Conversation, Project, Workspace, WorkspaceNode } from "./api";

type SidebarProps = {
  activePage: "agent" | "mcp";
  mode: AppMode;
  conversations: Conversation[];
  currentId: string | null;
  projects: Project[];
  currentProjectId: string | null;
  workspace: Workspace | null;
  selectedPath: string | null;
  modifiedFiles: string[];
  onCreate: () => void;
  onOpenMcpServers: () => void;
  onSelectConversation: (id: string) => void;
  onDeleteConversation: (id: string) => void;
  onSelectProject: (path: string) => void;
  onOpenFolder: () => void;
  onRefreshWorkspace: () => void;
  onSelectFile: (path: string) => void;
};

function formatTime(value: string) {
  return new Date(value).toLocaleString([], {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function FileTree({
  nodes,
  depth,
  expanded,
  selectedPath,
  modifiedFiles,
  onToggle,
  onSelectFile,
}: {
  nodes: WorkspaceNode[];
  depth: number;
  expanded: Set<string>;
  selectedPath: string | null;
  modifiedFiles: Set<string>;
  onToggle: (path: string) => void;
  onSelectFile: (path: string) => void;
}) {
  return (
    <>
      {nodes.map((node) => {
        const isDirectory = node.type === "directory";
        const isExpanded = expanded.has(node.path);
        return (
          <div key={node.path}>
            <button
              className={`tree-row ${selectedPath === node.path ? "selected" : ""}`}
              style={{ paddingLeft: 10 + depth * 16 }}
              title={node.path}
              onClick={() => (isDirectory ? onToggle(node.path) : onSelectFile(node.path))}
            >
              <span className="tree-chevron">
                {isDirectory ? isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} /> : null}
              </span>
              {isDirectory ? <Folder size={15} /> : <File size={15} />}
              <span className="tree-name">{node.name}</span>
              {modifiedFiles.has(node.path) ? <span className="modified-dot" title="本次任务已修改" /> : null}
            </button>
            {isDirectory && isExpanded && node.children?.length ? (
              <FileTree
                nodes={node.children}
                depth={depth + 1}
                expanded={expanded}
                selectedPath={selectedPath}
                modifiedFiles={modifiedFiles}
                onToggle={onToggle}
                onSelectFile={onSelectFile}
              />
            ) : null}
          </div>
        );
      })}
    </>
  );
}

export default function Sidebar({
  activePage,
  mode,
  conversations,
  currentId,
  projects,
  currentProjectId,
  workspace,
  selectedPath,
  modifiedFiles,
  onCreate,
  onOpenMcpServers,
  onSelectConversation,
  onDeleteConversation,
  onSelectProject,
  onOpenFolder,
  onRefreshWorkspace,
  onSelectFile,
}: SidebarProps) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  useEffect(() => {
    setExpanded(new Set(workspace?.tree.filter((node) => node.type === "directory").slice(0, 3).map((node) => node.path)));
  }, [workspace?.root]);

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
            className={item.id === currentProjectId && mode === "project" ? "active" : ""}
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
      ) : mode === "chat" ? (
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
      ) : (
        <>
          <div className="project-actions">
            <button className="open-project-button" onClick={onOpenFolder}>
              <FolderOpen size={16} />
              <span>{workspace ? "更换文件夹" : "打开文件夹"}</span>
            </button>
            <button className="icon-button" title="刷新文件树" disabled={!workspace} onClick={onRefreshWorkspace}>
              <RefreshCw size={16} />
            </button>
          </div>
          {workspace ? (
            <>
              <div className="workspace-heading" title={workspace.root}>
                <FolderOpen size={16} />
                <div>
                  <strong>{workspace.name}</strong>
                  <span>{workspace.entry_count} 项</span>
                </div>
              </div>
              <div className="file-tree">
                <FileTree
                  nodes={workspace.tree}
                  depth={0}
                  expanded={expanded}
                  selectedPath={selectedPath}
                  modifiedFiles={new Set(modifiedFiles)}
                  onToggle={(path) => {
                    setExpanded((current) => {
                      const next = new Set(current);
                      if (next.has(path)) next.delete(path);
                      else next.add(path);
                      return next;
                    });
                  }}
                  onSelectFile={onSelectFile}
                />
                {workspace.truncated ? <div className="tree-note">目录较大，已省略部分文件</div> : null}
              </div>
            </>
          ) : (
            <div className="sidebar-empty">
              <Folder size={28} />
              <span>尚未打开项目</span>
              <small>打开后可浏览和预览代码</small>
            </div>
          )}
        </>
      )}
    </aside>
  );
}
