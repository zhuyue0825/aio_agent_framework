create table mcp_server_connections (
    id uuid primary key,
    owner_id uuid not null references app_users(id) on delete cascade,
    kind varchar(40) not null,
    display_name varchar(120) not null,
    enabled boolean not null default true,
    config_json text not null default '{}',
    encrypted_secret text not null,
    status varchar(20) not null,
    last_checked_at timestamptz,
    last_error_code varchar(80),
    created_at timestamptz not null,
    updated_at timestamptz not null,
    version bigint not null default 0,
    constraint uq_mcp_server_owner_kind unique (owner_id, kind)
);

create index idx_mcp_server_owner_updated
    on mcp_server_connections(owner_id, updated_at desc);
