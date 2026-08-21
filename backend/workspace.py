from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from agent_framework.tools import Tool, ToolRegistry, object_schema


IGNORED_NAMES = {
    ".cache",
    ".git",
    ".hf-home",
    ".idea",
    ".next",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".venv-train",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "target",
}
MAX_TREE_ENTRIES = 1200
MAX_TREE_DEPTH = 8
MAX_FILE_BYTES = 1_500_000
MAX_SNAPSHOT_FILES = 8000
VISIBLE_HIDDEN_NAMES = {".codex", ".github", ".openai", ".vscode"}
ALLOWED_ROOTS_ENV = "AIO_ALLOWED_WORKSPACE_ROOTS"


class WorkspaceError(ValueError):
    pass


def allowed_workspace_roots() -> tuple[Path, ...]:
    configured = os.environ.get(ALLOWED_ROOTS_ENV, "")
    if not configured.strip():
        raise RuntimeError(f"{ALLOWED_ROOTS_ENV} must contain at least one absolute directory")

    roots: list[Path] = []
    for value in configured.split(os.pathsep):
        if not value.strip():
            continue
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            raise RuntimeError(f"{ALLOWED_ROOTS_ENV} entries must be absolute paths")
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as exc:
            raise RuntimeError(f"Configured workspace root is unavailable: {candidate}") from exc
        if not resolved.is_dir():
            raise RuntimeError(f"Configured workspace root is not a directory: {candidate}")
        roots.append(resolved)

    if not roots:
        raise RuntimeError(f"{ALLOWED_ROOTS_ENV} must contain at least one absolute directory")
    return tuple(dict.fromkeys(roots))


def workspace_boundary(path: Path) -> Path | None:
    matches: list[Path] = []
    for allowed_root in allowed_workspace_roots():
        try:
            path.relative_to(allowed_root)
            matches.append(allowed_root)
        except ValueError:
            continue
    return max(matches, key=lambda item: len(item.parts), default=None)


def should_ignore(name: str) -> bool:
    return name in IGNORED_NAMES or (name.startswith(".") and name not in VISIBLE_HIDDEN_NAMES)


def _success(message: str, data: Any, hint: str | None = None) -> dict[str, Any]:
    return {"success": True, "message": message, "data": data, "hint": hint}


def _failure(message: str, error: str, hint: str | None = None) -> dict[str, Any]:
    return {"success": False, "message": message, "error": error, "data": None, "hint": hint}


def normalize_workspace_root(path: str) -> Path:
    if not path.strip():
        raise WorkspaceError("文件夹路径不能为空")
    try:
        root = Path(path).expanduser().resolve(strict=True)
    except OSError as exc:
        raise WorkspaceError("文件夹不存在或不可访问") from exc
    if not root.is_dir():
        raise WorkspaceError("所选路径不是文件夹")
    if workspace_boundary(root) is None:
        raise WorkspaceError("该目录不在允许的工作区范围内")
    if not os.access(root, os.R_OK):
        raise WorkspaceError("文件夹不可读")
    return root


def resolve_workspace_path(root: Path, relative_path: str, *, must_exist: bool = True) -> Path:
    candidate = Path(relative_path).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise WorkspaceError("路径超出当前项目文件夹") from exc
    if must_exist and not resolved.exists():
        raise WorkspaceError(f"文件不存在: {relative_path}")
    return resolved


def relative_workspace_path(root: Path, path: Path) -> str:
    relative = path.relative_to(root).as_posix()
    return relative if relative != "." else ""


def list_directories(path: str | None = None) -> dict[str, Any]:
    current = normalize_workspace_root(path) if path else allowed_workspace_roots()[0]
    boundary = workspace_boundary(current)
    if boundary is None:
        raise WorkspaceError("该目录不在允许的工作区范围内")

    directories: list[dict[str, str]] = []
    try:
        entries = sorted(current.iterdir(), key=lambda item: item.name.casefold())
    except PermissionError as exc:
        raise WorkspaceError("没有权限读取该目录") from exc

    for entry in entries:
        if entry.name.startswith(".") or entry.is_symlink():
            continue
        try:
            if entry.is_dir() and os.access(entry, os.R_OK):
                directories.append({"name": entry.name, "path": str(entry)})
        except OSError:
            continue
        if len(directories) >= 300:
            break

    parent = None if current == boundary else str(current.parent)
    return {
        "path": str(current),
        "name": current.name or str(current),
        "parent": parent,
        "directories": directories,
    }


def build_workspace_tree(root: Path) -> dict[str, Any]:
    state = {"count": 0, "truncated": False}

    def walk(directory: Path, depth: int) -> list[dict[str, Any]]:
        if depth > MAX_TREE_DEPTH or state["count"] >= MAX_TREE_ENTRIES:
            state["truncated"] = True
            return []
        try:
            entries = sorted(
                directory.iterdir(),
                key=lambda item: (not item.is_dir(), item.name.casefold()),
            )
        except (OSError, PermissionError):
            return []

        nodes: list[dict[str, Any]] = []
        for entry in entries:
            if should_ignore(entry.name) or entry.is_symlink():
                continue
            if state["count"] >= MAX_TREE_ENTRIES:
                state["truncated"] = True
                break
            try:
                is_dir = entry.is_dir()
                stat = entry.stat()
            except OSError:
                continue

            state["count"] += 1
            node: dict[str, Any] = {
                "name": entry.name,
                "path": relative_workspace_path(root, entry),
                "type": "directory" if is_dir else "file",
                "modified_at": stat.st_mtime,
            }
            if is_dir:
                node["children"] = walk(entry, depth + 1)
            else:
                node["size"] = stat.st_size
            nodes.append(node)
        return nodes

    return {
        "root": str(root),
        "name": root.name or str(root),
        "tree": walk(root, 0),
        "entry_count": state["count"],
        "truncated": state["truncated"],
    }


def read_workspace_file(root: Path, relative_path: str) -> dict[str, Any]:
    path = resolve_workspace_path(root, relative_path)
    if not path.is_file():
        raise WorkspaceError(f"路径不是文件: {relative_path}")
    size = path.stat().st_size
    if size > MAX_FILE_BYTES:
        raise WorkspaceError(f"文件超过预览上限 {MAX_FILE_BYTES // 1_000_000}MB")
    raw = path.read_bytes()
    if b"\x00" in raw[:8192]:
        raise WorkspaceError("二进制文件暂不支持代码预览")
    return {
        "path": relative_workspace_path(root, path),
        "name": path.name,
        "content": raw.decode("utf-8", errors="replace"),
        "size": size,
        "modified_at": path.stat().st_mtime,
        "language": language_for_file(path),
    }


def write_workspace_file(root: Path, relative_path: str, content: str) -> dict[str, Any]:
    path = resolve_workspace_path(root, relative_path, must_exist=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return read_workspace_file(root, relative_workspace_path(root, path))


def language_for_file(path: Path) -> str:
    by_name = {
        "Dockerfile": "dockerfile",
        "Makefile": "makefile",
        "package.json": "json",
        "tsconfig.json": "json",
    }
    if path.name in by_name:
        return by_name[path.name]
    return {
        ".css": "css",
        ".go": "go",
        ".html": "html",
        ".java": "java",
        ".js": "javascript",
        ".json": "json",
        ".md": "markdown",
        ".py": "python",
        ".rs": "rust",
        ".sh": "shell",
        ".sql": "sql",
        ".tsx": "typescript",
        ".ts": "typescript",
        ".yaml": "yaml",
        ".yml": "yaml",
    }.get(path.suffix.lower(), "text")


def snapshot_workspace(root: Path) -> dict[str, tuple[int, int]]:
    snapshot: dict[str, tuple[int, int]] = {}
    for directory, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if not should_ignore(name)]
        base = Path(directory)
        for filename in filenames:
            path = base / filename
            if path.is_symlink():
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            snapshot[relative_workspace_path(root, path)] = (stat.st_mtime_ns, stat.st_size)
            if len(snapshot) >= MAX_SNAPSHOT_FILES:
                return snapshot
    return snapshot


def changed_workspace_files(
    before: dict[str, tuple[int, int]],
    after: dict[str, tuple[int, int]],
) -> list[str]:
    return sorted(path for path, signature in after.items() if before.get(path) != signature)


class WorkspaceTools:
    def __init__(self, root: Path) -> None:
        self.root = root

    def list_files(self, relative_path: str = "") -> dict[str, Any]:
        try:
            directory = resolve_workspace_path(self.root, relative_path or ".")
            if not directory.is_dir():
                raise WorkspaceError(f"路径不是目录: {relative_path}")
            entries: list[dict[str, Any]] = []
            for entry in sorted(directory.iterdir(), key=lambda item: (not item.is_dir(), item.name.casefold())):
                if should_ignore(entry.name) or entry.is_symlink():
                    continue
                entries.append(
                    {
                        "name": entry.name,
                        "path": relative_workspace_path(self.root, entry),
                        "type": "directory" if entry.is_dir() else "file",
                    }
                )
                if len(entries) >= 300:
                    break
            return _success("目录读取完成", {"path": relative_path, "entries": entries})
        except WorkspaceError as exc:
            return _failure(str(exc), "list_failed")
        except OSError:
            return _failure("目录读取失败", "list_failed")

    def read_file(self, relative_path: str) -> dict[str, Any]:
        try:
            return _success("文件读取完成", read_workspace_file(self.root, relative_path))
        except WorkspaceError as exc:
            return _failure(str(exc), "read_failed")
        except OSError:
            return _failure("文件读取失败", "read_failed")

    def write_file(self, relative_path: str, content: str) -> dict[str, Any]:
        try:
            file = write_workspace_file(self.root, relative_path, content)
            return _success(
                "文件写入完成",
                {
                    "path": file["path"],
                    "bytes": len(content.encode("utf-8")),
                },
            )
        except WorkspaceError as exc:
            return _failure(str(exc), "write_failed")
        except OSError:
            return _failure("文件写入失败", "write_failed")

    def search_files(self, query: str) -> dict[str, Any]:
        if not query:
            return _failure("搜索内容不能为空", "empty_query")
        matches: list[dict[str, Any]] = []
        try:
            for directory, dirnames, filenames in os.walk(self.root):
                dirnames[:] = [name for name in dirnames if not should_ignore(name)]
                for filename in filenames:
                    path = Path(directory) / filename
                    if path.is_symlink() or path.stat().st_size > MAX_FILE_BYTES:
                        continue
                    raw = path.read_bytes()
                    if b"\x00" in raw[:8192]:
                        continue
                    for line_number, line in enumerate(raw.decode("utf-8", errors="replace").splitlines(), 1):
                        if query.casefold() in line.casefold():
                            matches.append(
                                {
                                    "path": relative_workspace_path(self.root, path),
                                    "line": line_number,
                                    "text": line[:500],
                                }
                            )
                            if len(matches) >= 100:
                                return _success("搜索完成，结果已截断", {"matches": matches, "truncated": True})
            return _success("搜索完成", {"matches": matches, "truncated": False})
        except OSError:
            return _failure("文件搜索失败", "search_failed")


def build_workspace_tools(root: Path) -> ToolRegistry:
    handlers = WorkspaceTools(root)
    registry = ToolRegistry()
    registry.register(
        Tool(
            name="list_files",
            description="List files and folders inside the opened project. Paths are relative to the project root.",
            parameters=object_schema(
                {"path": {"type": "string", "description": "Relative directory path; use an empty string for root."}},
                ["path"],
            ),
            handler=lambda args: handlers.list_files(args.get("path", "")),
        )
    )
    registry.register(
        Tool(
            name="file_read",
            description="Read a UTF-8 text file inside the opened project using a relative path.",
            parameters=object_schema(
                {"file": {"type": "string", "description": "Relative file path inside the project."}},
                ["file"],
            ),
            handler=lambda args: handlers.read_file(args["file"]),
        )
    )
    registry.register(
        Tool(
            name="file_write",
            description="Create or overwrite a UTF-8 text file inside the opened project using a relative path.",
            parameters=object_schema(
                {
                    "file": {"type": "string", "description": "Relative file path inside the project."},
                    "content": {"type": "string", "description": "Complete file content to write."},
                },
                ["file", "content"],
            ),
            handler=lambda args: handlers.write_file(args["file"], args["content"]),
        )
    )
    registry.register(
        Tool(
            name="search_files",
            description="Search text across files in the opened project.",
            parameters=object_schema(
                {"query": {"type": "string", "description": "Text to find, case-insensitive."}},
                ["query"],
            ),
            handler=lambda args: handlers.search_files(args["query"]),
        )
    )
    return registry
