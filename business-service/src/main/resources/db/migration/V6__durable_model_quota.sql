create table model_daily_quotas (
    user_id uuid not null references app_users(id) on delete cascade,
    provider varchar(20) not null,
    quota_date date not null,
    used integer not null,
    updated_at timestamptz not null,
    primary key (user_id, provider, quota_date),
    constraint ck_model_daily_quotas_provider check (provider = 'remote'),
    constraint ck_model_daily_quotas_used check (used >= 0)
);

create index idx_model_daily_quotas_date
    on model_daily_quotas(quota_date);
