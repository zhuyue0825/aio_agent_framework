package com.aioagent.business.run;

import com.aioagent.business.agent.AgentServiceClient;
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
    private final AgentCancellationPublisher cancellationPublisher;
    private final AgentServiceClient agentService;

    public AgentRunRecovery(
            AgentRunRepository runs,
            AgentRunService service,
            AgentRunDispatcher dispatcher,
            AppProperties properties,
            AgentCancellationPublisher cancellationPublisher,
            AgentServiceClient agentService) {
        this.runs = runs;
        this.service = service;
        this.dispatcher = dispatcher;
        this.properties = properties;
        this.cancellationPublisher = cancellationPublisher;
        this.agentService = agentService;
    }

    @EventListener(ApplicationReadyEvent.class)
    public void recoverOnStartup() {
        sweep();
    }

    @Scheduled(fixedDelayString = "${app.agent.recovery-sweep-interval:30s}")
    public void sweep() {
        Instant now = Instant.now();
        for (AgentRun stale : runs.findAllByStatusAndLeaseExpiresAtBeforeOrderByLeaseExpiresAtAsc(
                RunStatus.RUNNING, now)) {
            if (service.expireStaleRun(stale.getId(), now)) {
                cancellationPublisher.publish(stale.getId());
                try {
                    agentService.cancel(stale.getId(), stale.getTraceId());
                } catch (RuntimeException exception) {
                    log.atWarn()
                            .addKeyValue("run_id", stale.getId())
                            .log("stale_agent_run_cancellation_failed", exception);
                }
                log.atWarn().addKeyValue("run_id", stale.getId()).log("recovered_stale_agent_run");
            }
        }
        Instant changeCutoff = now.minus(properties.getAgent().getChangeApplyStaleAfter());
        for (AgentRun applying : runs.findAllByChangeStatusAndChangeApplyStartedAtBeforeOrderByChangeApplyStartedAtAsc(
                "APPLYING", changeCutoff)) {
            if (service.expireStaleChangeApply(applying.getId(), changeCutoff)) {
                log.atWarn().addKeyValue("run_id", applying.getId()).log("recovered_stale_change_apply");
            }
        }
        for (AgentRun pending : runs.findDispatchable(RunStatus.PENDING, now)) {
            submit(pending.getId());
        }
    }

    public void submit(UUID runId) {
        String dispatchToken = UUID.randomUUID().toString();
        if (!service.claimDispatch(runId, dispatchToken)) {
            return;
        }
        try {
            dispatcher.dispatch(runId, dispatchToken);
        } catch (TaskRejectedException exception) {
            service.releaseDispatch(runId, dispatchToken);
            service.fail(runId, RunStatus.FAILED, "RUN_QUEUE_FULL", "任务队列已满，请稍后重试");
            log.atWarn().addKeyValue("run_id", runId).log("agent_run_queue_rejected");
        } catch (RuntimeException exception) {
            service.releaseDispatch(runId, dispatchToken);
            log.atWarn().addKeyValue("run_id", runId).log("agent_run_dispatch_failed", exception);
        }
    }
}
