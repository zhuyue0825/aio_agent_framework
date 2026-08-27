from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from backend.mcp_servers.qq_mail import QqMailMcpServer
from backend.mcp_servers.registry import build_mcp_server_tools


class FakeImap:
    selections: list[str] = []
    searches: list[tuple[Any, ...]] = []
    summary_fetches: list[str] = []
    headers = {
        "101": (
            b"Subject: =?utf-8?b?5Lya6K6u6YCa55+l?=\r\n"
            b"From: teammate@example.com\r\n"
            b"To: 12****@qq.com\r\n"
            b"Date: Fri, 10 Jul 2020 17:30:22 +0800\r\n"
            b"Message-ID: <mail-101@example.com>\r\n\r\n"
        ),
        "102": (
            b"Subject: Weekly report\r\n"
            b"From: mentor@example.com\r\n"
            b"To: 12****@qq.com\r\n"
            b"Date: Wed, 27 Aug 2026 11:00:00 +0800\r\n"
            b"Message-ID: <mail-102@example.com>\r\n\r\n"
        ),
    }
    internal_dates = {
        "101": "27-Aug-2026 12:00:00 +0800",
        "102": "26-Aug-2026 11:00:00 +0800",
    }

    def __init__(self, *_: Any, **__: Any) -> None:
        self.logged_in: tuple[str, str] | None = None

    def login(self, email: str, authorization_code: str) -> None:
        self.logged_in = (email, authorization_code)

    def list(self) -> tuple[str, list[bytes]]:
        return (
            "OK",
            [
                b'(\\HasNoChildren \\Inbox) "/" "INBOX"',
                b'(\\HasNoChildren) "/" "Archive"',
                b'(\\HasNoChildren \\Sent) "/" "&XfJT0ZAB-"',
                b'(\\Noselect) "/" "Groups"',
            ],
        )

    def select(self, mailbox: str, readonly: bool = False) -> tuple[str, list[bytes]]:
        assert readonly is True
        selected = mailbox[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        self.selections.append(selected)
        if selected not in {"INBOX", "Archive", "&XfJT0ZAB-"}:
            return "NO", [b"0"]
        return "OK", [b"2"]

    def uid(self, command: str, *args: Any) -> tuple[str, list[Any]]:
        if command == "search":
            self.searches.append(args)
            return "OK", [b"101 102"]
        uid_set = str(args[0])
        query = str(args[1])
        if "HEADER.FIELDS" in query:
            self.summary_fetches.append(uid_set)
            data: list[Any] = []
            for index, uid in enumerate(uid_set.split(","), start=1):
                metadata = (
                    f'{index} (UID {uid} INTERNALDATE "{self.internal_dates[uid]}" '
                    "FLAGS () RFC822.SIZE 2048)"
                ).encode()
                data.extend([(metadata, self.headers[uid]), b")"])
            return "OK", data
        uid = uid_set
        raw = self.headers[uid].replace(
            b"\r\n\r\n",
            b"\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n",
        ) + b"hello from qq mail"
        metadata = f'1 (UID {uid} INTERNALDATE "{self.internal_dates[uid]}")'.encode()
        return "OK", [(metadata, raw), b")"]

    def logout(self) -> None:
        return None


@pytest.fixture(autouse=True)
def fake_imap(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeImap.selections.clear()
    FakeImap.searches.clear()
    FakeImap.summary_fetches.clear()
    monkeypatch.setattr("backend.mcp_servers.qq_mail.imaplib.IMAP4_SSL", FakeImap)


def server() -> QqMailMcpServer:
    return QqMailMcpServer(email="123456@qq.com", authorization_code="secret-auth-code")


def test_lists_and_searches_mail_without_exposing_credentials() -> None:
    listed = server().call_tool("qq_mail_list_messages", {"limit": 2})
    assert listed["success"] is True
    assert [message["uid"] for message in listed["data"]["messages"]] == ["101", "102"]
    assert listed["data"]["messages"][0]["subject"] == "会议通知"
    assert listed["data"]["messages"][0]["received_at"] == "2026-08-27T12:00:00+08:00"
    assert listed["data"]["messages"][0]["header_date"].startswith("Fri, 10 Jul 2020")
    assert "date" not in listed["data"]["messages"][0]

    searched = server().call_tool("qq_mail_search_messages", {"from_address": "mentor", "limit": 10})
    assert searched["success"] is True
    assert [message["uid"] for message in searched["data"]["messages"]] == ["102"]
    assert searched["data"]["scan_truncated"] is False
    assert "secret-auth-code" not in str(listed)
    assert "123456@qq.com" not in str(listed)
    assert FakeImap.summary_fetches == ["101,102", "101,102"]


def test_lists_folders_and_uses_since_with_a_safe_folder(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "backend.mcp_servers.qq_mail._utc_now",
        lambda: datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc),
    )

    folders = server().call_tool("qq_mail_list_folders", {})
    assert folders["success"] is True
    assert [folder["id"] for folder in folders["data"]["folders"]] == [
        "INBOX",
        "Archive",
        "Groups",
        "&XfJT0ZAB-",
    ]
    assert folders["data"]["folders"][2]["selectable"] is False
    assert folders["data"]["folders"][3]["name"] == "已发送"

    listed = server().call_tool(
        "qq_mail_list_messages",
        {"folder": "Archive", "since_days": 5, "limit": 2},
    )
    assert listed["success"] is True
    assert listed["data"]["folder"] == {"id": "Archive", "name": "Archive"}
    assert all(message["folder_id"] == "Archive" for message in listed["data"]["messages"])
    assert FakeImap.searches[-1] == (None, "SINCE", "22-Aug-2026")
    assert FakeImap.selections[-1] == "Archive"


def test_rejects_invalid_date_and_folder_inputs() -> None:
    invalid_days = server().call_tool("qq_mail_list_messages", {"since_days": 0})
    assert invalid_days == {
        "success": False,
        "message": "since_days 必须是 1 到 3650 之间的整数",
        "error": "invalid_since_days",
    }
    assert server().call_tool("qq_mail_list_messages", {"since_days": 1.5})["error"] == "invalid_since_days"

    invalid_folder = server().call_tool("qq_mail_list_messages", {"folder": "Unknown"})
    assert invalid_folder["success"] is False
    assert invalid_folder["error"] == "invalid_folder"


def test_reads_message_body_and_registers_read_only_tools() -> None:
    read = server().call_tool("qq_mail_read_message", {"uid": "101"})
    assert read["success"] is True
    assert read["data"]["body"] == "hello from qq mail"
    assert read["data"]["received_at"] == "2026-08-27T12:00:00+08:00"
    assert read["data"]["header_date"].startswith("Fri, 10 Jul 2020")

    registry = build_mcp_server_tools(
        [
            {
                "kind": "qq_mail",
                "config": {"email": "123456@qq.com", "imap_host": "imap.qq.com", "imap_port": 993},
                "credentials": {"authorization_code": "secret-auth-code"},
            }
        ]
    )
    names = [spec["function"]["name"] for spec in registry.specs()]
    assert names == [
        "qq_mail_list_folders",
        "qq_mail_list_messages",
        "qq_mail_search_messages",
        "qq_mail_read_message",
    ]
    assert registry.call("qq_mail_read_message", {"uid": "101"})["success"] is True


def test_rejects_non_qq_imap_endpoint_to_prevent_ssrf() -> None:
    with pytest.raises(ValueError, match="only permits"):
        QqMailMcpServer(
            email="123456@qq.com",
            authorization_code="secret-auth-code",
            imap_host="127.0.0.1",
            imap_port=993,
        )
