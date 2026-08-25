alter table conversations
    add column version bigint not null default 0;

alter table agent_runs
    add column dispatched_at timestamptz,
    add column dispatch_token varchar(100),
    add column heartbeat_at timestamptz,
    add column lease_expires_at timestamptz,
    add column worker_id varchar(100),
    add column change_apply_started_at timestamptz,
    add column change_error_message text;

update agent_runs
set lease_expires_at = coalesce(started_at, created_at)
where status = 'RUNNING';

alter table agent_runs
    drop constraint if exists ck_agent_runs_change_status;

alter table agent_runs
    add constraint ck_agent_runs_change_status
    check (change_status in ('NONE', 'PROPOSED', 'APPLYING', 'APPLIED', 'APPLY_FAILED', 'REJECTED'));

create index idx_agent_runs_pending_lease
    on agent_runs(lease_expires_at, created_at)
    where status = 'PENDING';

create index idx_agent_runs_running_lease
    on agent_runs(lease_expires_at, started_at)
    where status = 'RUNNING';

create index idx_agent_runs_change_apply
    on agent_runs(change_status, change_apply_started_at)
    where change_status = 'APPLYING';
