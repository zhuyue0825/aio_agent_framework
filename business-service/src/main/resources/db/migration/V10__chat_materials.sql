CREATE TABLE chat_attachments (
 id UUID PRIMARY KEY,
 conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
 owner_id UUID NOT NULL REFERENCES app_users(id),
 project_id UUID REFERENCES projects(id) ON DELETE SET NULL,
 name VARCHAR(200) NOT NULL,
 source_kind VARCHAR(20) NOT NULL,
 source_path TEXT NOT NULL DEFAULT '',
 byte_size BIGINT NOT NULL,
 status VARCHAR(20) NOT NULL,
 error_message TEXT NOT NULL DEFAULT '',
 segments_json TEXT NOT NULL DEFAULT '[]',
 created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX chat_attachments_conversation ON chat_attachments(conversation_id,owner_id);
CREATE TABLE chat_knowledge_selection (
 conversation_id UUID PRIMARY KEY REFERENCES conversations(id) ON DELETE CASCADE,
 knowledge_ids_json TEXT NOT NULL DEFAULT '[]'
);
