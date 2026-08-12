create table app_users (
    id uuid primary key,
    username varchar(50) not null unique,
    password_hash varchar(100) not null,
    role varchar(20) not null,
    created_at timestamptz not null
);

create table projects (
    id uuid primary key,
    owner_id uuid not null references app_users(id),
    name varchar(120) not null,
    workspace_root text not null,
    created_at timestamptz not null,
    updated_at timestamptz not null,
    constraint uq_projects_owner_workspace unique (owner_id, workspace_root)
);

create table project_members (
    id uuid primary key,
    project_id uuid not null references projects(id) on delete cascade,
    user_id uuid not null references app_users(id) on delete cascade,
    member_role varchar(20) not null,
    created_at timestamptz not null,
    constraint uq_project_member unique (project_id, user_id)
);

create table conversations (
    id uuid primary key,
    owner_id uuid not null references app_users(id) on delete cascade,
    project_id uuid references projects(id) on delete set null,
    title varchar(80) not null,
    mode varchar(20) not null,
    created_at timestamptz not null,
    updated_at timestamptz not null
);

create table messages (
    id uuid primary key,
    conversation_id uuid not null references conversations(id) on delete cascade,
    role varchar(20) not null,
    content text not null,
    metadata_json text not null default '{}',
    created_at timestamptz not null
);

create index idx_conversations_owner_updated on conversations(owner_id, updated_at desc);
create index idx_messages_conversation_created on messages(conversation_id, created_at, id);

create table agent_runs (
    id uuid primary key,
    conversation_id uuid not null references conversations(id) on delete cascade,
    user_message_id uuid not null references messages(id) on delete cascade,
    project_id uuid references projects(id) on delete set null,
    requested_by_id uuid not null references app_users(id),
    status varchar(20) not null,
    task text not null,
    mode varchar(20) not null,
    approval_mode varchar(20) not null,
    max_history_messages integer not null,
    idempotency_key varchar(100) not null,
    trace_id varchar(100) not null,
    final_answer text,
    steps integer,
    changed_files_json text not null default '[]',
    error_code varchar(80),
    error_message text,
    cancel_requested boolean not null default false,
    created_at timestamptz not null,
    started_at timestamptz,
    finished_at timestamptz,
    version bigint not null default 0,
    constraint uq_agent_runs_idempotency unique (requested_by_id, idempotency_key),
    constraint ck_agent_runs_history check (max_history_messages between 0 and 30)
);

create unique index uq_agent_runs_active_conversation
    on agent_runs(conversation_id)
    where status in ('PENDING', 'RUNNING');
create index idx_agent_runs_user_created on agent_runs(requested_by_id, created_at desc);

create table run_events (
    id bigserial primary key,
    run_id uuid not null references agent_runs(id) on delete cascade,
    event_type varchar(80) not null,
    payload_json text not null default '{}',
    created_at timestamptz not null
);

create index idx_run_events_run_id on run_events(run_id, id);

create table legacy_imports (
    import_key varchar(120) primary key,
    completed_at timestamptz not null,
    conversations_imported integer not null,
    messages_imported integer not null
);
