alter table agent_runs
    add column model_provider varchar(20),
    add column model_name varchar(200),
    add column model_request_count integer not null default 0,
    add column input_tokens bigint,
    add column output_tokens bigint,
    add column model_latency_ms bigint not null default 0,
    add column attempt_count integer not null default 0;

create index idx_agent_runs_status_created on agent_runs(status, created_at);
create index idx_agent_runs_status_started on agent_runs(status, started_at);
create index idx_agent_runs_user_finished on agent_runs(requested_by_id, finished_at desc);
