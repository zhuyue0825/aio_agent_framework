import { FileCode2, Pencil, RefreshCw, Save, X } from "lucide-react";
import { useEffect, useState } from "react";
import type { WorkspaceFile } from "./api";

type CodePreviewProps = {
  file: WorkspaceFile;
  modified: boolean;
  saving: boolean;
  onRefresh: () => void;
  onClose: () => void;
  onSave: (content: string) => Promise<void>;
};

function formatBytes(size: number) {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

export default function CodePreview({
  file,
  modified,
  saving,
  onRefresh,
  onClose,
  onSave,
}: CodePreviewProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const lineNumbers = Array.from({ length: file.content.split("\n").length }, (_, index) => index + 1).join("\n");

  useEffect(() => {
    setDraft(file.content);
    setEditing(false);
  }, [file.path, file.modified_at, file.content]);

  return (
    <aside className="preview-panel">
      <header className="preview-header">
        <div className="preview-title">
          <FileCode2 size={17} />
          <span>{file.path}</span>
          {modified ? <span className="modified-badge">已修改</span> : null}
        </div>
        <div className="preview-actions">
          {editing ? (
            <>
              <button className="icon-button" title="取消编辑" disabled={saving} onClick={() => { setDraft(file.content); setEditing(false); }}>
                <X size={16} />
              </button>
              <button
                className="icon-button save-icon"
                title="保存文件"
                disabled={saving || draft === file.content}
                onClick={() => void onSave(draft).then(() => setEditing(false)).catch(() => undefined)}
              >
                <Save size={16} />
              </button>
            </>
          ) : (
            <>
              <button className="icon-button" title="编辑文件" onClick={() => setEditing(true)}>
                <Pencil size={15} />
              </button>
              <button className="icon-button" title="重新读取" onClick={onRefresh}>
                <RefreshCw size={15} />
              </button>
            </>
          )}
          <button className="icon-button" title="关闭预览" onClick={onClose}>
            <X size={16} />
          </button>
        </div>
      </header>
      <div className="file-meta">
        <span>{file.language}</span>
        <span>{formatBytes(file.size)}</span>
      </div>
      {editing ? (
        <textarea className="code-editor" value={draft} spellCheck={false} onChange={(event) => setDraft(event.target.value)} />
      ) : (
        <div className="code-scroll">
          <pre className="line-numbers" aria-hidden="true">{lineNumbers}</pre>
          <pre className="code-content"><code>{file.content}</code></pre>
        </div>
      )}
    </aside>
  );
}
