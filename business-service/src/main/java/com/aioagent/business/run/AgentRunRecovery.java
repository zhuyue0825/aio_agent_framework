package com.aioagent.business.run;

import com.aioagent.business.config.AppProperties;
import java.time.Instant;
import java.util.UUID;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.event.EventListener;
import org.springframework.core.task.TaskRejectedException;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.stereotype.Component;

@Component
public class AgentRunRecovery {

    private static final Logger log = LoggerFactory.getLogger(AgentRunRecovery.class);
    private final AgentRunRepository runs;
    private final AgentRunService service;
    private final AgentRunDispatcher dispatcher;
    private final AppProperties properties;

    public AgentRunRecovery(
            AgentRunRepository runs,
            AgentRunService service,
            AgentRunDispatcher dispatcher,
            AppProperties properties) {
        this.runs = runs;
        this.service = service;
        this.dispatcher = dispatcher;
        this.properties = properties;
    }

    @EventListener(ApplicationReadyEvent.class)
    public void recoverOnStartup() {
        sweep();
    }

    @Scheduled(fixedDelayString = "${app.agent.recovery-sweep-interval:30s}")
    public void sweep() {
        Instant cutoff = Instant.now().minus(properties.getAgent().getRecoveryStaleAfter());
        for (AgentRun stale : runs.findAllByStatusAndStartedAtBeforeOrderByStartedAtAsc(RunStatus.RUNNING, cutoff)) {
            service.fail(stale.getId(), RunStatus.FAILED, "RUN_INTERRUPTED", "服务重启或任务执行中断，请重新发送");
            log.atWarn().addKeyValue("run_id", stale.getId()).log("recovered_stale_agent_run");
        }
        for (AgentRun pending : runs.findAllByStatusOrderByCreatedAtAsc(RunStatus.PENDING)) {
            submit(pending.getId());
        }
    }

    public void submit(UUID runId) {
        try {
            dispatcher.dispatch(runId);
        } catch (TaskRejectedException exception) {
            service.fail(runId, RunStatus.FAILED, "RUN_QUEUE_FULL", "任务队列已满，请稍后重试");
            log.atWarn().addKeyValue("run_id", runId).log("agent_run_queue_rejected");
        }
    }
}
