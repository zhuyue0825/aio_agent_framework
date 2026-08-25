alter table conversations
    add column model_id varchar(200);

update conversations
set model_id = case
    when model_provider = 'REMOTE' then 'remote:deepseek'
    else 'local:minimind-64m'
end
where model_id is null;

alter table conversations
    alter column model_id set default 'local:minimind-64m',
    alter column model_id set not null;

create index idx_conversations_owner_model
    on conversations(owner_id, model_id);

alter table agent_runs
    add column model_id varchar(200);

update agent_runs
set model_id = case
    when model_provider = 'remote' then 'remote:deepseek'
    else 'local:minimind-64m'
end
where model_id is null;

alter table agent_runs
    alter column model_id set default 'local:minimind-64m',
    alter column model_id set not null;

create index idx_agent_runs_user_model_id_created
    on agent_runs(requested_by_id, model_id, created_at desc);
