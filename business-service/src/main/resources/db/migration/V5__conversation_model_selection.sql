alter table conversations
    add column model_provider varchar(20) not null default 'LOCAL';

alter table conversations
    add constraint ck_conversations_model_provider
    check (model_provider in ('LOCAL', 'REMOTE'));

update agent_runs
set model_provider = 'local'
where model_provider is null;

alter table agent_runs
    alter column model_provider set default 'local',
    alter column model_provider set not null;

alter table agent_runs
    add constraint ck_agent_runs_model_provider
    check (model_provider in ('local', 'remote'));

create index idx_agent_runs_user_model_created
    on agent_runs(requested_by_id, model_provider, created_at desc);
