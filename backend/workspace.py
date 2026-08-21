from __future__ import annotations

import os
import difflib
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
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
MULTI_TENANT_ENV = "AIO_MULTI_TENANT_WORKSPACES"
LOCAL_TEST_TOOL_ENV = "AIO_ENABLE_LOCAL_TEST_TOOL"


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


def multi_tenant_enabled() -> bool:
    return os.environ.get(MULTI_TENANT_ENV, "false").strip().lower() in {"1", "true", "yes", "on"}


def tenant_workspace_root(owner_id: str | None, *, create: bool = False) -> Path | None:
    if not multi_tenant_enabled():
        return None
    if not owner_id or not owner_id.strip():
        raise WorkspaceError("多用户工作区请求缺少用户标识")
    base = allowed_workspace_roots()[0]
    tenant = (base / owner_id.strip()).resolve(strict=False)
    try:
        tenant.relative_to(base)
    except ValueError as exc:
        raise WorkspaceError("用户工作区标识无效") from exc
    if create:
        tenant.mkdir(parents=True, exist_ok=True)
    if not tenant.exists() or not tenant.is_dir():
        raise WorkspaceError("用户工作区不存在")
    return tenant.resolve(strict=True)


def workspace_boundary(path: Path, owner_id: str | None = None) -> Path | None:
    tenant = tenant_workspace_root(owner_id, create=True)
    if tenant is not None:
        try:
            path.relative_to(tenant)
            return tenant
        except ValueError:
            return None
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


def normalize_workspace_root(path: str, owner_id: str | None = None) -> Path:
    if not path.strip():
        raise WorkspaceError("文件夹路径不能为空")
    try:
        root = Path(path).expanduser().resolve(strict=True)
    except OSError as exc:
        raise WorkspaceError("文件夹不存在或不可访问") from exc
    if not root.is_dir():
        raise WorkspaceError("所选路径不是文件夹")
    if workspace_boundary(root, owner_id) is None:
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


def list_directories(path: str | None = None, owner_id: str | None = None) -> dict[str, Any]:
    tenant = tenant_workspace_root(owner_id, create=True)
    current = normalize_workspace_root(path, owner_id) if path else tenant or allowed_workspace_roots()[0]
    boundary = workspace_boundary(current, owner_id)
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


def apply_workspace_changes(root: Path, changes: list[dict[str, str]]) -> list[str]:
    validated: list[tuple[Path, str, str]] = []
    for change in changes:
        relative_path = str(change.get("path") or "")
        expected_hash = str(change.get("original_sha256") or "")
        content = str(change.get("content") or "")
        if len(expected_hash) != 64:
            raise WorkspaceError("修改提案缺少有效的原文件哈希")
        path = resolve_workspace_path(root, relative_path, must_exist=False)
        original = path.read_bytes() if path.exists() and path.is_file() else b""
        if hashlib.sha256(original).hexdigest() != expected_hash:
            raise WorkspaceError(f"文件已在提案生成后发生变化: {relative_path}")
        if len(content.encode("utf-8")) > MAX_FILE_BYTES:
            raise WorkspaceError(f"文件超过 Agent 修改上限: {relative_path}")
        validated.append((path, content, relative_workspace_path(root, path)))

    temporary_files: list[tuple[Path, Path]] = []
    try:
        for path, content, _ in validated:
            path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary_name = tempfile.mkstemp(prefix=".aio-agent-", suffix=".tmp", dir=path.parent)
            temporary = Path(temporary_name)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            temporary_files.append((temporary, path))
        for temporary, path in temporary_files:
            os.replace(temporary, path)
        return [relative for _, _, relative in validated]
    finally:
        for temporary, _ in temporary_files:
            temporary.unlink(missing_ok=True)


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
        self._staged: dict[str, str] = {}
        self._original_hashes: dict[str, str] = {}

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
            normalized = relative_workspace_path(
                self.root,
                resolve_workspace_path(self.root, relative_path, must_exist=relative_path not in self._staged),
            )
            if normalized in self._staged:
                content = self._staged[normalized]
                return _success(
                    "文件读取完成（包含待确认修改）",
                    {
                        "path": normalized,
                        "name": Path(normalized).name,
                        "content": content,
                        "size": len(content.encode("utf-8")),
                        "language": language_for_file(Path(normalized)),
                        "staged": True,
                    },
                )
            return _success("文件读取完成", read_workspace_file(self.root, relative_path))
        except WorkspaceError as exc:
            return _failure(str(exc), "read_failed")
        except OSError:
            return _failure("文件读取失败", "read_failed")

    def write_file(self, relative_path: str, content: str) -> dict[str, Any]:
        try:
            normalized = self._stage(relative_path, content)
            return _success(
                "修改已暂存，等待用户查看 diff 后确认",
                {
                    "path": normalized,
                    "bytes": len(content.encode("utf-8")),
                    "diff": self._diff_for(normalized),
                    "requires_confirmation": True,
                },
            )
        except WorkspaceError as exc:
            return _failure(str(exc), "write_failed")
        except OSError:
            return _failure("文件写入失败", "write_failed")

    def apply_patch(self, relative_path: str, old_text: str, new_text: str, replace_all: bool = False) -> dict[str, Any]:
        try:
            normalized = relative_workspace_path(
                self.root,
                resolve_workspace_path(self.root, relative_path, must_exist=bool(old_text)),
            )
            if normalized in self._staged:
                current = self._staged[normalized]
            elif old_text:
                current = read_workspace_file(self.root, normalized)["content"]
            else:
                current = ""
            occurrences = current.count(old_text) if old_text else 0
            if old_text and occurrences == 0:
                return _failure("未找到要替换的原文，文件可能已经变化", "patch_context_missing")
            if old_text and occurrences > 1 and not replace_all:
                return _failure("原文出现多次，请提供更完整上下文或明确 replace_all", "patch_context_ambiguous")
            updated = current.replace(old_text, new_text, -1 if replace_all else 1) if old_text else new_text
            normalized = self._stage(normalized, updated)
            return _success(
                "补丁已暂存，等待用户确认",
                {
                    "path": normalized,
                    "diff": self._diff_for(normalized),
                    "requires_confirmation": True,
                },
            )
        except WorkspaceError as exc:
            return _failure(str(exc), "patch_failed")
        except OSError:
            return _failure("补丁暂存失败", "patch_failed")

    def git_diff(self) -> dict[str, Any]:
        diffs = [self._diff_for(path) for path in sorted(self._staged)]
        return _success(
            "待确认修改 diff 已生成",
            {"diff": "\n".join(diff for diff in diffs if diff), "files": sorted(self._staged)},
        )

    def run_tests(self, suite: str = "auto") -> dict[str, Any]:
        commands = self._test_commands(suite)
        if not commands:
            return _failure("未识别到可安全执行的测试命令", "test_command_unavailable")
        try:
            with tempfile.TemporaryDirectory(prefix="aio-agent-test-") as directory:
                target = Path(directory) / "workspace"
                test_home = Path(directory) / "home"
                test_home.mkdir(mode=0o700)
                shutil.copytree(
                    self.root,
                    target,
                    ignore=shutil.ignore_patterns(*IGNORED_NAMES, ".git", "node_modules", "target", "dist"),
                )
                for relative_path, content in self._staged.items():
                    destination = resolve_workspace_path(target, relative_path, must_exist=False)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_text(content, encoding="utf-8")
                results: list[dict[str, Any]] = []
                success = True
                child_environment = {
                    "CI": "true",
                    "HOME": str(test_home),
                    "LANG": os.environ.get("LANG", "C.UTF-8"),
                    "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
                    "PYTHONNOUSERSITE": "1",
                    "TMPDIR": str(Path(directory)),
                }
                for command, cwd in commands:
                    completed = subprocess.run(
                        command,
                        cwd=target / cwd,
                        capture_output=True,
                        text=True,
                        timeout=180,
                        check=False,
                        env=child_environment,
                    )
                    output = (completed.stdout + "\n" + completed.stderr).strip()
                    results.append(
                        {
                            "command": command,
                            "exit_code": completed.returncode,
                            "output": output[-12_000:],
                        }
                    )
                    success = success and completed.returncode == 0
                    if not success:
                        break
                return {
                    "success": success,
                    "message": "测试通过" if success else "测试失败",
                    "data": {"results": results, "tested_staged_changes": True},
                    "hint": None,
                }
        except subprocess.TimeoutExpired:
            return _failure("测试执行超时", "test_timeout")
        except (OSError, WorkspaceError) as exc:
            return _failure("测试环境创建失败", f"test_setup_failed:{type(exc).__name__}")

    def proposals(self) -> list[dict[str, Any]]:
        return [
            {
                "path": path,
                "original_sha256": self._original_hashes[path],
                "content": content,
                "diff": self._diff_for(path),
            }
            for path, content in sorted(self._staged.items())
        ]

    def _stage(self, relative_path: str, content: str) -> str:
        path = resolve_workspace_path(self.root, relative_path, must_exist=False)
        normalized = relative_workspace_path(self.root, path)
        if normalized not in self._original_hashes:
            original = path.read_bytes() if path.exists() and path.is_file() else b""
            if len(original) > MAX_FILE_BYTES:
                raise WorkspaceError("文件超过 Agent 修改上限")
            self._original_hashes[normalized] = hashlib.sha256(original).hexdigest()
        if len(content.encode("utf-8")) > MAX_FILE_BYTES:
            raise WorkspaceError("文件超过 Agent 修改上限")
        self._staged[normalized] = content
        return normalized

    def _diff_for(self, relative_path: str) -> str:
        path = resolve_workspace_path(self.root, relative_path, must_exist=False)
        original = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
        staged = self._staged[relative_path]
        return "".join(
            difflib.unified_diff(
                original.splitlines(keepends=True),
                staged.splitlines(keepends=True),
                fromfile=f"a/{relative_path}",
                tofile=f"b/{relative_path}",
            )
        )

    def _test_commands(self, suite: str) -> list[tuple[list[str], str]]:
        allowed = {"auto", "python", "frontend", "java"}
        if suite not in allowed:
            return []
        commands: list[tuple[list[str], str]] = []
        if suite in {"auto", "python"} and (self.root / "backend" / "tests").is_dir():
            commands.append(([sys.executable, "-m", "pytest", "-q", "backend/tests"], ""))
        elif suite in {"auto", "python"} and (self.root / "tests").is_dir():
            commands.append(([sys.executable, "-m", "pytest", "-q"], ""))
        if suite in {"auto", "frontend"}:
            frontend = self.root / "frontend" if (self.root / "frontend" / "package.json").exists() else self.root
            package_path = frontend / "package.json"
            if package_path.exists() and shutil.which("npm"):
                package = json.loads(package_path.read_text(encoding="utf-8"))
                scripts = package.get("scripts") if isinstance(package.get("scripts"), dict) else {}
                script = "test" if "test" in scripts else "build" if "build" in scripts else None
                frontend_path = relative_workspace_path(self.root, frontend)
                if script and (frontend / "package-lock.json").exists():
                    commands.append(
                        (["npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund"], frontend_path)
                    )
                    commands.append(
                        (["npm", "run", script, "--", "--run"] if script == "test" else ["npm", "run", script], frontend_path)
                    )
        if suite in {"auto", "java"}:
            java_root = self.root / "business-service" if (self.root / "business-service" / "mvnw").exists() else self.root
            if (java_root / "mvnw").exists():
                commands.append((["./mvnw", "--batch-mode", "--no-transfer-progress", "test"], relative_workspace_path(self.root, java_root)))
        return commands

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


def build_workspace_tools(root: Path) -> tuple[ToolRegistry, WorkspaceTools]:
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
            name="apply_patch",
            description=(
                "Stage an exact text replacement without writing to disk. Read the file first and provide enough old_text "
                "context to identify one location. The user must confirm the resulting diff before it is applied."
            ),
            parameters=object_schema(
                {
                    "file": {"type": "string", "description": "Relative file path."},
                    "old_text": {"type": "string", "description": "Exact existing text; empty only for a new file."},
                    "new_text": {"type": "string", "description": "Replacement text."},
                    "replace_all": {"type": "boolean", "description": "Replace every match; defaults to false."},
                },
                ["file", "old_text", "new_text"],
            ),
            handler=lambda args: handlers.apply_patch(
                args["file"], args["old_text"], args["new_text"], bool(args.get("replace_all", False))
            ),
        )
    )
    registry.register(
        Tool(
            name="git_diff",
            description="Show every staged Agent change that still requires user confirmation.",
            parameters=object_schema({}, []),
            handler=lambda _args: handlers.git_diff(),
        )
    )
    if os.environ.get(LOCAL_TEST_TOOL_ENV, "false").strip().lower() in {"1", "true", "yes", "on"}:
        registry.register(
            Tool(
                name="run_tests",
                description=(
                    "Run one fixed test command against a temporary copy containing staged changes. "
                    "This tool is available only for trusted local workspaces."
                ),
                parameters=object_schema(
                    {"suite": {"type": "string", "enum": ["auto", "python", "frontend", "java"]}},
                    ["suite"],
                ),
                handler=lambda args: handlers.run_tests(args["suite"]),
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
    return registry, handlers
