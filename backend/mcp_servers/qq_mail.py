from __future__ import annotations

import base64
import imaplib
import re
import ssl
from datetime import datetime, timedelta, timezone
from email import message_from_bytes
from email.header import decode_header
from email.message import Message
from html import unescape
from typing import Any

from agent_framework.tools import object_schema


QQ_IMAP_HOST = "imap.qq.com"
QQ_IMAP_PORT = 993
MAX_LIST_LIMIT = 30
MAX_SEARCH_SCAN = 200
MAX_SINCE_DAYS = 3_650
SUMMARY_FETCH_BATCH_SIZE = 50
MAX_BODY_CHARS = 8_000
MAX_FETCH_BYTES = 262_144

_LIST_RESPONSE = re.compile(
    rb'^\((?P<flags>[^)]*)\)\s+(?P<delimiter>NIL|"(?:\\[^\r\n]|[^"\\\r\n])*")\s+(?P<mailbox>.+)$'
)
_INTERNALDATE = re.compile(rb'INTERNALDATE\s+"(?P<value>[^"]+)"', re.IGNORECASE)
_UID = re.compile(rb'UID\s+(?P<value>\d+)', re.IGNORECASE)
_IMAP_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


class QqMailConnectionError(RuntimeError):
    """A sanitized QQ Mail connection failure safe to return across service boundaries."""


class QqMailInputError(ValueError):
    """A caller-correctable tool input failure safe to return to the model."""

    def __init__(self, message: str, code: str) -> None:
        super().__init__(message)
        self.code = code


class QqMailMcpServer:
    """Built-in, read-only MCP tool provider for a single QQ mailbox."""

    def __init__(
        self,
        *,
        email: str,
        authorization_code: str,
        imap_host: str = QQ_IMAP_HOST,
        imap_port: int = QQ_IMAP_PORT,
        timeout_seconds: float = 15.0,
    ) -> None:
        normalized_host = imap_host.strip().lower()
        if normalized_host != QQ_IMAP_HOST or imap_port != QQ_IMAP_PORT:
            raise ValueError("QQ Mail connector only permits imap.qq.com:993")
        self.email = email.strip().lower()
        self.authorization_code = authorization_code.strip()
        self.imap_host = normalized_host
        self.imap_port = imap_port
        self.timeout_seconds = timeout_seconds

    def initialize(self) -> dict[str, Any]:
        return {
            "protocolVersion": "2025-06-18",
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "aio-qq-mail", "version": "0.1.0"},
        }

    def list_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "qq_mail_list_folders",
                "description": "列出当前 QQ 邮箱可访问的邮件目录。返回的目录 id 可用于其他 QQ 邮箱工具。只读。",
                "inputSchema": object_schema({}, []),
                "annotations": {"readOnlyHint": True, "destructiveHint": False},
            },
            {
                "name": "qq_mail_list_messages",
                "description": (
                    "按服务器收件时间列出 QQ 邮箱目录中的最近邮件摘要。"
                    "received_at 是服务器收件时间，header_date 是邮件声明的日期。只读，不会修改已读状态。"
                ),
                "inputSchema": object_schema(
                    {
                        "limit": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": MAX_LIST_LIMIT,
                            "default": 10,
                            "description": "最多返回的邮件数量。",
                        },
                        "unread_only": {
                            "type": "boolean",
                            "default": False,
                            "description": "是否只列出未读邮件。",
                        },
                        "since_days": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": MAX_SINCE_DAYS,
                            "description": "可选。只返回过去 N×24 小时内收到的邮件，例如最近五天传 5。",
                        },
                        "folder": {
                            "type": "string",
                            "maxLength": 256,
                            "default": "INBOX",
                            "description": "邮箱目录 id 或名称；使用 qq_mail_list_folders 获取，默认 INBOX。",
                        },
                    },
                    [],
                ),
                "annotations": {"readOnlyHint": True, "destructiveHint": False},
            },
            {
                "name": "qq_mail_search_messages",
                "description": (
                    "在指定 QQ 邮箱目录中按关键词、发件人或主题搜索邮件摘要。"
                    "查询日期必须使用 since_days；keyword 不会匹配日期。结果按服务器收件时间倒序。"
                    "为控制延迟，每次最多扫描该目录最近 200 封候选邮件，并通过 scan_truncated 明示是否截断。只读。"
                ),
                "inputSchema": object_schema(
                    {
                        "keyword": {
                            "type": "string",
                            "maxLength": 200,
                            "description": "在发件人、收件人和主题中匹配的关键词。",
                        },
                        "from_address": {
                            "type": "string",
                            "maxLength": 254,
                            "description": "可选的发件人地址或名称。",
                        },
                        "subject": {
                            "type": "string",
                            "maxLength": 200,
                            "description": "可选的主题关键词。",
                        },
                        "limit": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": MAX_LIST_LIMIT,
                            "default": 10,
                        },
                        "since_days": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": MAX_SINCE_DAYS,
                            "description": "可选。只搜索过去 N×24 小时内收到的邮件。",
                        },
                        "folder": {
                            "type": "string",
                            "maxLength": 256,
                            "default": "INBOX",
                            "description": "邮箱目录 id 或名称；使用 qq_mail_list_folders 获取，默认 INBOX。",
                        },
                    },
                    [],
                ),
                "annotations": {"readOnlyHint": True, "destructiveHint": False},
            },
            {
                "name": "qq_mail_read_message",
                "description": (
                    "按 UID 和所在目录读取一封 QQ 邮件的正文与附件元数据。"
                    "UID 只在对应目录内有效，应传入邮件摘要返回的 folder_id。只读，不下载附件。"
                ),
                "inputSchema": object_schema(
                    {
                        "uid": {
                            "type": "string",
                            "pattern": "^[0-9]+$",
                            "description": "由邮件列表或搜索工具返回的 UID。",
                        },
                        "folder": {
                            "type": "string",
                            "maxLength": 256,
                            "default": "INBOX",
                            "description": "邮件摘要返回的 folder_id，默认 INBOX。",
                        },
                    },
                    ["uid"],
                ),
                "annotations": {"readOnlyHint": True, "destructiveHint": False},
            },
        ]

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            if name == "qq_mail_list_folders":
                return self._list_folders()
            if name == "qq_mail_list_messages":
                return self._list_messages(
                    limit=_bounded_limit(arguments.get("limit", 10)),
                    unread_only=bool(arguments.get("unread_only", False)),
                    since_days=_since_days(arguments.get("since_days")),
                    folder=_folder_argument(arguments.get("folder")),
                )
            if name == "qq_mail_search_messages":
                return self._search_messages(
                    keyword=_clean(arguments.get("keyword")),
                    from_address=_clean(arguments.get("from_address")),
                    subject=_clean(arguments.get("subject")),
                    limit=_bounded_limit(arguments.get("limit", 10)),
                    since_days=_since_days(arguments.get("since_days")),
                    folder=_folder_argument(arguments.get("folder")),
                )
            if name == "qq_mail_read_message":
                uid = str(arguments.get("uid", ""))
                if not uid.isdigit():
                    return _failure("邮件 UID 必须是数字", "invalid_uid")
                return self._read_message(uid, folder=_folder_argument(arguments.get("folder")))
            return _failure(f"未知的 QQ 邮箱工具：{name}", "unknown_tool")
        except QqMailInputError as exc:
            return _failure(str(exc), exc.code)
        except (imaplib.IMAP4.error, OSError, ssl.SSLError, QqMailConnectionError):
            return _failure(
                "QQ 邮箱暂时无法访问，请检查连接状态和授权码",
                "qq_mail_unavailable",
            )

    def test_connection(self) -> int:
        client = self._connect()
        try:
            status, data = client.select(_quote_mailbox("INBOX"), readonly=True)
            if status != "OK":
                raise QqMailConnectionError("Unable to select mailbox")
            return int(data[0]) if data and data[0] else 0
        finally:
            _logout(client)

    def _connect(self) -> imaplib.IMAP4_SSL:
        try:
            client = imaplib.IMAP4_SSL(
                self.imap_host,
                self.imap_port,
                ssl_context=ssl.create_default_context(),
                timeout=self.timeout_seconds,
            )
            client.login(self.email, self.authorization_code)
            return client
        except (imaplib.IMAP4.error, OSError, ssl.SSLError) as exc:
            raise QqMailConnectionError("QQ Mail login failed") from exc

    def _list_folders(self) -> dict[str, Any]:
        client = self._connect()
        try:
            folders = self._fetch_folders(client)
            return _success(
                f"已读取 {len(folders)} 个邮箱目录",
                {"account": _mask_email(self.email), "folders": folders},
            )
        finally:
            _logout(client)

    def _list_messages(
        self,
        *,
        limit: int,
        unread_only: bool,
        since_days: int | None,
        folder: str,
    ) -> dict[str, Any]:
        client = self._connect()
        try:
            selected_folder = self._select_folder(client, folder)
            now = _utc_now()
            cutoff = now - timedelta(days=since_days) if since_days is not None else None
            criteria = ["UNSEEN"] if unread_only else []
            if cutoff is not None:
                criteria.extend(("SINCE", _imap_date(cutoff)))
            uids = self._search_uids(client, *(criteria or ["ALL"]))
            candidate_count = min(len(uids), max(limit * 2, limit))
            summaries = self._fetch_summaries(client, uids[-candidate_count:])
            messages = self._prepare_summaries(
                summaries,
                folder=selected_folder,
                cutoff=cutoff,
                limit=limit,
            )
            return _success(
                f"已读取 {len(messages)} 封邮件摘要",
                {
                    "account": _mask_email(self.email),
                    "folder": _folder_view(selected_folder),
                    "messages": messages,
                    "unread_only": unread_only,
                    "since_days": since_days,
                },
            )
        finally:
            _logout(client)

    def _search_messages(
        self,
        *,
        keyword: str,
        from_address: str,
        subject: str,
        limit: int,
        since_days: int | None,
        folder: str,
    ) -> dict[str, Any]:
        client = self._connect()
        try:
            selected_folder = self._select_folder(client, folder)
            now = _utc_now()
            cutoff = now - timedelta(days=since_days) if since_days is not None else None
            criteria: list[str] = []
            if cutoff is not None:
                criteria.extend(("SINCE", _imap_date(cutoff)))
            candidate_uids = self._search_uids(client, *(criteria or ["ALL"]))
            uids = candidate_uids[-MAX_SEARCH_SCAN:]
            summaries = self._prepare_summaries(
                self._fetch_summaries(client, uids),
                folder=selected_folder,
                cutoff=cutoff,
                limit=MAX_SEARCH_SCAN,
            )
            matched: list[dict[str, Any]] = []
            for summary in summaries:
                haystack = " ".join(
                    str(summary.get(field, "")) for field in ("subject", "from", "to")
                ).casefold()
                if keyword and keyword.casefold() not in haystack:
                    continue
                if from_address and from_address.casefold() not in str(summary.get("from", "")).casefold():
                    continue
                if subject and subject.casefold() not in str(summary.get("subject", "")).casefold():
                    continue
                matched.append(summary)
                if len(matched) >= limit:
                    break
            return _success(
                f"找到 {len(matched)} 封匹配邮件"
                + ("（候选邮件较多，仅扫描最近 200 封）" if len(candidate_uids) > len(uids) else ""),
                {
                    "account": _mask_email(self.email),
                    "folder": _folder_view(selected_folder),
                    "messages": matched,
                    "since_days": since_days,
                    "candidate_count": len(candidate_uids),
                    "scanned_count": len(uids),
                    "scan_truncated": len(candidate_uids) > len(uids),
                },
            )
        finally:
            _logout(client)

    def _read_message(self, uid: str, *, folder: str) -> dict[str, Any]:
        client = self._connect()
        try:
            selected_folder = self._select_folder(client, folder)
            status, data = client.uid(
                "fetch",
                uid,
                f"(UID INTERNALDATE BODY.PEEK[]<0.{MAX_FETCH_BYTES}>)",
            )
            raw = _extract_fetch_bytes(status, data)
            if raw is None:
                return _failure("没有找到这封邮件", "message_not_found")
            message = message_from_bytes(raw)
            body, truncated = _extract_body(message)
            attachments = _attachment_metadata(message)
            return _success(
                "邮件读取完成",
                {
                    "uid": uid,
                    "folder_id": selected_folder["id"],
                    "folder_name": selected_folder["name"],
                    "subject": _decode_header_value(message.get("Subject")),
                    "from": _decode_header_value(message.get("From")),
                    "to": _decode_header_value(message.get("To")),
                    "received_at": _extract_internaldate(data),
                    "header_date": _decode_header_value(message.get("Date")),
                    "message_id": _decode_header_value(message.get("Message-ID")),
                    "body": body,
                    "body_truncated": truncated,
                    "attachments": attachments,
                },
            )
        finally:
            _logout(client)

    def _select_folder(self, client: imaplib.IMAP4_SSL, requested: str) -> dict[str, Any]:
        if requested.casefold() == "inbox":
            selected = {
                "id": "INBOX",
                "name": "INBOX",
                "flags": ["\\Inbox"],
                "selectable": True,
                "default": True,
            }
        else:
            folders = self._fetch_folders(client)
            matches = [
                item
                for item in folders
                if requested == item["id"] or requested.casefold() == item["name"].casefold()
            ]
            if len(matches) != 1 or not matches[0]["selectable"]:
                raise QqMailInputError(
                    "邮箱目录不存在、不可选择或名称不唯一，请先调用 qq_mail_list_folders",
                    "invalid_folder",
                )
            selected = matches[0]
        status, _ = client.select(_quote_mailbox(selected["id"]), readonly=True)
        if status != "OK":
            raise QqMailInputError("邮箱目录当前不可访问", "invalid_folder")
        return selected

    def _fetch_folders(self, client: imaplib.IMAP4_SSL) -> list[dict[str, Any]]:
        status, data = client.list()
        if status != "OK" or not data:
            raise QqMailConnectionError("Unable to list mailboxes")
        folders = [folder for item in data if (folder := _parse_folder(item)) is not None]
        if not folders:
            raise QqMailConnectionError("No usable mailboxes returned")
        return sorted(folders, key=lambda item: (not item["default"], item["name"].casefold()))

    def _search_uids(self, client: imaplib.IMAP4_SSL, *criteria: str) -> list[str]:
        status, data = client.uid("search", None, *criteria)
        if status != "OK" or not data:
            raise QqMailConnectionError("Unable to search mailbox")
        return data[0].decode("ascii", errors="ignore").split()

    def _fetch_summaries(
        self,
        client: imaplib.IMAP4_SSL,
        uids: list[str],
    ) -> list[dict[str, Any]]:
        summaries: list[dict[str, Any]] = []
        for offset in range(0, len(uids), SUMMARY_FETCH_BATCH_SIZE):
            batch = uids[offset : offset + SUMMARY_FETCH_BATCH_SIZE]
            if not batch:
                continue
            status, data = client.uid(
                "fetch",
                ",".join(batch),
                "(UID INTERNALDATE BODY.PEEK[HEADER.FIELDS (SUBJECT FROM TO DATE MESSAGE-ID)] FLAGS RFC822.SIZE)",
            )
            if status != "OK" or not isinstance(data, list):
                raise QqMailConnectionError("Unable to fetch message summaries")
            summaries.extend(
                summary
                for item in data
                if isinstance(item, tuple) and (summary := _summary_from_fetch_item(item)) is not None
            )
        return summaries

    def _prepare_summaries(
        self,
        summaries: list[dict[str, Any]],
        *,
        folder: dict[str, Any],
        cutoff: datetime | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        prepared: list[dict[str, Any]] = []
        for summary in summaries:
            received = _received_datetime(summary.get("received_at"))
            if cutoff is not None and (received is None or received < cutoff):
                continue
            prepared.append(
                {
                    **summary,
                    "folder_id": folder["id"],
                    "folder_name": folder["name"],
                }
            )
        prepared.sort(key=_summary_sort_key, reverse=True)
        return prepared[:limit]


def _summary_from_fetch_item(item: tuple[Any, ...]) -> dict[str, Any] | None:
    if len(item) < 2 or not isinstance(item[0], bytes) or not isinstance(item[1], bytes):
        return None
    metadata, raw = item[0], item[1]
    uid_match = _UID.search(metadata)
    if not uid_match:
        return None
    message = message_from_bytes(raw)
    size_match = re.search(rb"RFC822\.SIZE\s+(\d+)", metadata)
    flags_match = re.search(rb"FLAGS\s+\(([^)]*)\)", metadata)
    flags = flags_match.group(1).decode("ascii", errors="ignore").split() if flags_match else []
    return {
        "uid": uid_match.group("value").decode("ascii"),
        "subject": _decode_header_value(message.get("Subject")),
        "from": _decode_header_value(message.get("From")),
        "to": _decode_header_value(message.get("To")),
        "received_at": _internaldate_from_metadata(metadata),
        "header_date": _decode_header_value(message.get("Date")),
        "message_id": _decode_header_value(message.get("Message-ID")),
        "unread": "\\Seen" not in flags,
        "size": int(size_match.group(1)) if size_match else None,
    }


def _since_days(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not (
        isinstance(value, int) or (isinstance(value, str) and value.isdigit())
    ):
        raise QqMailInputError("since_days 必须是 1 到 3650 之间的整数", "invalid_since_days")
    parsed = int(value)
    if parsed < 1 or parsed > MAX_SINCE_DAYS:
        raise QqMailInputError("since_days 必须是 1 到 3650 之间的整数", "invalid_since_days")
    return parsed


def _folder_argument(value: Any) -> str:
    folder = str(value or "INBOX").strip()
    if not folder:
        return "INBOX"
    if len(folder) > 256 or any(character in folder for character in ("\r", "\n", "\x00")):
        raise QqMailInputError("邮箱目录参数无效", "invalid_folder")
    return folder


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _imap_date(value: datetime) -> str:
    return f"{value.day:02d}-{_IMAP_MONTHS[value.month - 1]}-{value.year:04d}"


def _folder_view(folder: dict[str, Any]) -> dict[str, str]:
    return {"id": str(folder["id"]), "name": str(folder["name"])}


def _parse_folder(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, bytes):
        return None
    match = _LIST_RESPONSE.match(item)
    if not match:
        return None
    mailbox_bytes = _unquote_imap_token(match.group("mailbox"))
    try:
        mailbox_id = mailbox_bytes.decode("ascii")
    except UnicodeDecodeError:
        return None
    if not mailbox_id or any(character in mailbox_id for character in ("\r", "\n", "\x00")):
        return None
    flags = match.group("flags").decode("ascii", errors="ignore").split()
    lowered_flags = {flag.casefold() for flag in flags}
    delimiter_token = match.group("delimiter")
    delimiter = None
    if delimiter_token != b"NIL":
        delimiter = _unquote_imap_token(delimiter_token).decode("ascii", errors="ignore")
    default = mailbox_id.casefold() == "inbox" or "\\inbox" in lowered_flags
    return {
        "id": mailbox_id,
        "name": _decode_modified_utf7(mailbox_id),
        "delimiter": delimiter,
        "flags": flags,
        "selectable": "\\noselect" not in lowered_flags,
        "default": default,
    }


def _unquote_imap_token(value: bytes) -> bytes:
    if len(value) < 2 or not value.startswith(b'"') or not value.endswith(b'"'):
        return value
    output = bytearray()
    escaped = False
    for byte in value[1:-1]:
        if escaped:
            output.append(byte)
            escaped = False
        elif byte == ord("\\"):
            escaped = True
        else:
            output.append(byte)
    if escaped:
        output.append(ord("\\"))
    return bytes(output)


def _decode_modified_utf7(value: str) -> str:
    decoded: list[str] = []
    cursor = 0
    try:
        while cursor < len(value):
            marker = value.find("&", cursor)
            if marker < 0:
                decoded.append(value[cursor:])
                break
            decoded.append(value[cursor:marker])
            end = value.find("-", marker)
            if end < 0:
                return value
            token = value[marker + 1 : end]
            if not token:
                decoded.append("&")
            else:
                encoded = token.replace(",", "/")
                encoded += "=" * ((4 - len(encoded) % 4) % 4)
                decoded.append(base64.b64decode(encoded).decode("utf-16-be"))
            cursor = end + 1
    except (UnicodeDecodeError, ValueError):
        return value
    return "".join(decoded)


def _quote_mailbox(value: str) -> str:
    if any(character in value for character in ("\r", "\n", "\x00")):
        raise QqMailInputError("邮箱目录参数无效", "invalid_folder")
    try:
        value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise QqMailInputError("邮箱目录 id 必须来自 qq_mail_list_folders", "invalid_folder") from exc
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _extract_internaldate(data: Any) -> str | None:
    if not isinstance(data, list):
        return None
    metadata = b" ".join(
        item[0]
        for item in data
        if isinstance(item, tuple) and item and isinstance(item[0], bytes)
    )
    return _internaldate_from_metadata(metadata)


def _internaldate_from_metadata(metadata: bytes) -> str | None:
    match = _INTERNALDATE.search(metadata)
    if not match:
        return None
    try:
        received = datetime.strptime(
            match.group("value").decode("ascii"),
            "%d-%b-%Y %H:%M:%S %z",
        )
    except (UnicodeDecodeError, ValueError):
        return None
    return received.isoformat()


def _received_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        received = datetime.fromisoformat(value)
    except ValueError:
        return None
    if received.tzinfo is None:
        return received.replace(tzinfo=timezone.utc)
    return received


def _summary_sort_key(summary: dict[str, Any]) -> tuple[float, int]:
    received = _received_datetime(summary.get("received_at"))
    uid = str(summary.get("uid", ""))
    return (
        received.timestamp() if received is not None else float("-inf"),
        int(uid) if uid.isdigit() else 0,
    )


def _bounded_limit(value: Any) -> int:
    try:
        return max(1, min(MAX_LIST_LIMIT, int(value)))
    except (TypeError, ValueError):
        return 10


def _clean(value: Any) -> str:
    return str(value or "").strip()[:200]


def _extract_fetch_bytes(status: str, data: Any) -> bytes | None:
    if status != "OK" or not isinstance(data, list):
        return None
    for item in data:
        if isinstance(item, tuple) and len(item) > 1 and isinstance(item[1], bytes):
            return item[1]
    return None


def _decode_header_value(value: str | None) -> str:
    if not value:
        return ""
    decoded: list[str] = []
    for part, encoding in decode_header(value):
        if isinstance(part, bytes):
            for candidate in (encoding, "utf-8", "gb18030", "latin-1"):
                if not candidate:
                    continue
                try:
                    decoded.append(part.decode(candidate, errors="strict"))
                    break
                except (LookupError, UnicodeDecodeError):
                    continue
            else:
                decoded.append(part.decode("utf-8", errors="replace"))
        else:
            decoded.append(part)
    return "".join(decoded).strip()


def _extract_body(message: Message) -> tuple[str, bool]:
    plain: list[str] = []
    html: list[str] = []
    parts = message.walk() if message.is_multipart() else [message]
    for part in parts:
        if part.get_content_disposition() == "attachment":
            continue
        content_type = part.get_content_type()
        if content_type not in {"text/plain", "text/html"}:
            continue
        payload = part.get_payload(decode=True)
        if not isinstance(payload, bytes):
            continue
        charset = part.get_content_charset() or "utf-8"
        try:
            text = payload.decode(charset, errors="replace")
        except LookupError:
            text = payload.decode("utf-8", errors="replace")
        (plain if content_type == "text/plain" else html).append(text)
    body = "\n".join(plain).strip()
    if not body and html:
        body = _html_to_text("\n".join(html))
    truncated = len(body) > MAX_BODY_CHARS
    return body[:MAX_BODY_CHARS], truncated


def _html_to_text(value: str) -> str:
    value = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
    value = re.sub(r"(?i)<br\s*/?>", "\n", value)
    value = re.sub(r"(?i)</p\s*>", "\n", value)
    return re.sub(r"[ \t]+", " ", unescape(re.sub(r"(?s)<[^>]+>", " ", value))).strip()


def _attachment_metadata(message: Message) -> list[dict[str, Any]]:
    attachments: list[dict[str, Any]] = []
    for part in message.walk():
        filename = _decode_header_value(part.get_filename())
        if not filename:
            continue
        payload = part.get_payload(decode=True)
        attachments.append(
            {
                "filename": filename,
                "content_type": part.get_content_type(),
                "size": len(payload) if isinstance(payload, bytes) else None,
            }
        )
    return attachments[:50]


def _mask_email(value: str) -> str:
    local, separator, domain = value.partition("@")
    if not separator:
        return "****"
    return f"{local[:2]}****@{domain}"


def _logout(client: imaplib.IMAP4_SSL) -> None:
    try:
        client.logout()
    except (imaplib.IMAP4.error, OSError):
        pass


def _success(message: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"success": True, "message": message, "data": data}


def _failure(message: str, error: str) -> dict[str, Any]:
    return {"success": False, "message": message, "error": error}
