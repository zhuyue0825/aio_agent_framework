import { ArrowUp, Folder, FolderOpen, X } from "lucide-react";
import { useEffect, useState } from "react";
import { api, type DirectoryListing } from "./api";

type FolderPickerProps = {
  open: boolean;
  initialPath?: string;
  onClose: () => void;
  onOpen: (path: string) => Promise<void>;
};

export default function FolderPicker({ open, initialPath, onClose, onOpen }: FolderPickerProps) {
  const [listing, setListing] = useState<DirectoryListing | null>(null);
  const [pathDraft, setPathDraft] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function navigate(path?: string) {
    setLoading(true);
    setError(null);
    try {
      const data = await api.listDirectories(path);
      setListing(data);
      setPathDraft(data.path);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (open) void navigate(initialPath);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, initialPath]);

  if (!open) return null;

  return (
    <div className="dialog-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section className="folder-dialog" role="dialog" aria-modal="true" aria-labelledby="folder-dialog-title">
        <header className="dialog-header">
          <div>
            <h2 id="folder-dialog-title">打开项目文件夹</h2>
            <p>Agent 只会读取和修改你打开的这个目录。</p>
          </div>
          <button className="icon-button" title="关闭" onClick={onClose}>
            <X size={18} />
          </button>
        </header>
        <div className="path-row">
          <button className="icon-button" title="上一级" disabled={!listing?.parent || loading} onClick={() => void navigate(listing?.parent ?? undefined)}>
            <ArrowUp size={17} />
          </button>
          <input
            value={pathDraft}
            aria-label="文件夹路径"
            onChange={(event) => setPathDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") void navigate(pathDraft);
            }}
          />
          <button disabled={loading || !pathDraft.trim()} onClick={() => void navigate(pathDraft)}>
            前往
          </button>
        </div>
        <div className="directory-list">
          {loading ? <div className="directory-state">正在读取文件夹...</div> : null}
          {!loading && error ? <div className="directory-state error-text">{error}</div> : null}
          {!loading && !error && listing?.directories.length === 0 ? (
            <div className="directory-state">这个目录下没有子文件夹</div>
          ) : null}
          {!loading && !error
            ? listing?.directories.map((directory) => (
                <button key={directory.path} className="directory-row" onDoubleClick={() => void navigate(directory.path)} onClick={() => setPathDraft(directory.path)}>
                  <Folder size={18} />
                  <span>{directory.name}</span>
                </button>
              ))
            : null}
        </div>
        <footer className="dialog-footer">
          <div className="selected-directory" title={pathDraft}>
            <FolderOpen size={16} />
            <span>{pathDraft || "未选择"}</span>
          </div>
          <button onClick={onClose}>取消</button>
          <button className="primary" disabled={!pathDraft.trim() || loading} onClick={() => void onOpen(pathDraft)}>
            打开此文件夹
          </button>
        </footer>
      </section>
    </div>
  );
}
