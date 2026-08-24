create table refresh_tokens (
    id uuid primary key,
    user_id uuid not null references app_users(id) on delete cascade,
    token_hash varchar(64) not null unique,
    created_at timestamptz not null,
    expires_at timestamptz not null,
    revoked_at timestamptz
);

create index idx_refresh_tokens_user on refresh_tokens(user_id, expires_at desc);
create index idx_refresh_tokens_expiry on refresh_tokens(expires_at);

create table password_reset_tokens (
    id uuid primary key,
    user_id uuid not null references app_users(id) on delete cascade,
    token_hash varchar(64) not null unique,
    created_at timestamptz not null,
    expires_at timestamptz not null,
    used_at timestamptz
);

create index idx_password_reset_tokens_expiry on password_reset_tokens(expires_at);
