import {
  ChevronDown,
  ChevronRight,
  File,
  Folder,
  FolderOpen,
  Plus,
  RefreshCw,
  Trash2,
} from "lucide-react";
import { useEffect, useState } from "react";
import type { AppMode, Conversation, Workspace, WorkspaceNode } from "./api";

type SidebarProps = {
  mode: AppMode;
  conversations: Conversation[];
  currentId: string | null;
  workspace: Workspace | null;
  selectedPath: string | null;
  modifiedFiles: string[];
  onCreate: () => void;
  onSelectConversation: (id: string) => void;
  onDeleteConversation: (id: string) => void;
  onOpenFolder: () => void;
  onRefreshWorkspace: () => void;
  onSelectFile: (path: string) => void;
};

function formatTime(value: number) {
  return new Date(value * 1000).toLocaleString([], {
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
  mode,
  conversations,
  currentId,
  workspace,
  selectedPath,
  modifiedFiles,
  onCreate,
  onSelectConversation,
  onDeleteConversation,
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
      <div className="brand">
        <div className="brand-mark">A</div>
        <div>
          <div className="brand-title">AIO Agent</div>
          <div className="brand-subtitle">Local workspace</div>
        </div>
        <button className="icon-button brand-action" title="新对话" onClick={onCreate}>
          <Plus size={17} />
        </button>
      </div>

      {mode === "chat" ? (
        <>
          <div className="section-heading">
            <span>对话记录</span>
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
