alter table agent_runs
    add column proposed_changes_json text not null default '[]',
    add column change_status varchar(20) not null default 'NONE',
    add column changes_applied_at timestamptz;

alter table agent_runs
    add constraint ck_agent_runs_change_status
    check (change_status in ('NONE', 'PROPOSED', 'APPLIED', 'REJECTED'));
