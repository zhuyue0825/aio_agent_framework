from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any


class AppDB:
    def __init__(self, path: str | None = None) -> None:
        root = Path(__file__).resolve().parents[1]
        self.path = Path(path) if path else root / "data" / "app.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                create table if not exists conversations (
                    id text primary key,
                    title text not null,
                    created_at real not null,
                    updated_at real not null
                );

                create table if not exists messages (
                    id text primary key,
                    conversation_id text not null references conversations(id) on delete cascade,
                    role text not null,
                    content text not null,
                    metadata_json text not null default '{}',
                    created_at real not null
                );

                create index if not exists idx_messages_conversation_created
                    on messages(conversation_id, created_at);
                """
            )

    def list_conversations(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select c.*,
                       (select count(*) from messages m where m.conversation_id = c.id) as message_count
                from conversations c
                order by c.updated_at desc
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def create_conversation(self, title: str = "新对话") -> dict[str, Any]:
        now = time.time()
        conversation = {
            "id": str(uuid.uuid4()),
            "title": title,
            "created_at": now,
            "updated_at": now,
        }
        with self._connect() as conn:
            conn.execute(
                "insert into conversations(id, title, created_at, updated_at) values(?, ?, ?, ?)",
                (conversation["id"], conversation["title"], conversation["created_at"], conversation["updated_at"]),
            )
        return conversation

    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("select * from conversations where id = ?", (conversation_id,)).fetchone()
        return dict(row) if row else None

    def update_conversation_title(self, conversation_id: str, title: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "update conversations set title = ?, updated_at = ? where id = ?",
                (title, time.time(), conversation_id),
            )

    def delete_conversation(self, conversation_id: str) -> None:
        with self._connect() as conn:
            conn.execute("delete from messages where conversation_id = ?", (conversation_id,))
            conn.execute("delete from conversations where id = ?", (conversation_id,))

    def list_messages(self, conversation_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select * from messages
                where conversation_id = ?
                order by created_at asc
                """,
                (conversation_id,),
            ).fetchall()
        return [self._message_from_row(row) for row in rows]

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = time.time()
        message = {
            "id": str(uuid.uuid4()),
            "conversation_id": conversation_id,
            "role": role,
            "content": content,
            "metadata": metadata or {},
            "created_at": now,
        }
        with self._connect() as conn:
            conn.execute(
                """
                insert into messages(id, conversation_id, role, content, metadata_json, created_at)
                values(?, ?, ?, ?, ?, ?)
                """,
                (
                    message["id"],
                    conversation_id,
                    role,
                    content,
                    json.dumps(message["metadata"], ensure_ascii=False),
                    now,
                ),
            )
            conn.execute(
                "update conversations set updated_at = ? where id = ?",
                (now, conversation_id),
            )
        return message

    def _message_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        metadata_json = data.pop("metadata_json", "{}")
        try:
            data["metadata"] = json.loads(metadata_json)
        except json.JSONDecodeError:
            data["metadata"] = {}
        return data
