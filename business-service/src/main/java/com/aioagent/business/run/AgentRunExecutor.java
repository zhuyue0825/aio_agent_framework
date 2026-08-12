package com.aioagent.business.run;

import com.aioagent.business.agent.AgentServiceClient;
import com.aioagent.business.agent.AgentServiceException;
import java.util.Optional;
import java.util.UUID;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.slf4j.MDC;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Service;

@Service
public class AgentRunExecutor {

    private static final Logger log = LoggerFactory.getLogger(AgentRunExecutor.class);
    private final AgentRunService runs;
    private final AgentServiceClient agentService;

    public AgentRunExecutor(AgentRunService runs, AgentServiceClient agentService) {
        this.runs = runs;
        this.agentService = agentService;
    }

    @Async("agentTaskExecutor")
    public void execute(UUID runId) {
        Optional<AgentRunService.PreparedExecution> optional = runs.prepare(runId);
        if (optional.isEmpty()) {
            return;
        }
        AgentRunService.PreparedExecution prepared = optional.get();
        MDC.put("traceId", prepared.traceId());
        try {
            AgentServiceClient.ExecutionRequest request = new AgentServiceClient.ExecutionRequest(
                    prepared.runId(),
                    prepared.task(),
                    prepared.mode().name().toLowerCase(),
                    prepared.history(),
                    prepared.workspaceRoot(),
                    prepared.approvalMode(),
                    prepared.maxSteps(),
                    prepared.traceId(),
                    agentService.callbackUrl(runId));
            runs.complete(runId, agentService.execute(request));
        } catch (AgentServiceException exception) {
            log.warn("Agent run {} failed: {}", runId, exception.getMessage());
            if (exception.isTimeout()) {
                try {
                    agentService.cancel(runId, prepared.traceId());
                } catch (Exception cancelError) {
                    log.debug("Remote cancellation after timeout failed", cancelError);
                }
                runs.fail(runId, RunStatus.TIMED_OUT, "AGENT_TIMEOUT", "Agent 执行超时");
            } else {
                runs.fail(runId, RunStatus.FAILED, "AGENT_SERVICE_ERROR", exception.getMessage());
            }
        } catch (Exception exception) {
            log.error("Unexpected agent run failure", exception);
            runs.fail(runId, RunStatus.FAILED, "RUN_EXECUTION_ERROR", exception.getMessage());
        } finally {
            MDC.remove("traceId");
        }
    }
}
