package com.aioagent.business.run;

import com.aioagent.business.agent.AgentServiceClient;
import com.aioagent.business.agent.AgentServiceException;
import com.aioagent.business.config.AppProperties;
import java.util.Optional;
import java.util.UUID;
import java.util.concurrent.ScheduledFuture;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.slf4j.MDC;
import org.springframework.scheduling.TaskScheduler;
import org.springframework.stereotype.Service;

@Service
public class AgentRunExecutor {

    private static final Logger log = LoggerFactory.getLogger(AgentRunExecutor.class);
    private final AgentRunService runs;
    private final AgentServiceClient agentService;
    private final TaskScheduler scheduler;
    private final AppProperties properties;
    private final String workerId = UUID.randomUUID().toString();

    public AgentRunExecutor(
            AgentRunService runs,
            AgentServiceClient agentService,
            TaskScheduler scheduler,
            AppProperties properties) {
        this.runs = runs;
        this.agentService = agentService;
        this.scheduler = scheduler;
        this.properties = properties;
    }

    public void execute(UUID runId, String dispatchToken) {
        Optional<AgentRunService.PreparedExecution> optional = runs.prepare(runId, dispatchToken, workerId);
        if (optional.isEmpty()) {
            return;
        }
        AgentRunService.PreparedExecution prepared = optional.get();
        ScheduledFuture<?> heartbeat = startHeartbeat(runId);
        MDC.put("trace_id", prepared.traceId());
        try {
            AgentServiceClient.ExecutionRequest request = new AgentServiceClient.ExecutionRequest(
                    prepared.runId(),
                    prepared.task(),
                    prepared.mode().name().toLowerCase(),
                    prepared.modelProvider(),
                    prepared.history(),
                    prepared.workspaceRoot(),
                    prepared.approvalMode(),
                    prepared.maxSteps(),
                    prepared.traceId(),
                    prepared.requestedById(),
                    prepared.workspaceOwnerId(),
                    agentService.callbackUrl(runId));
            runs.complete(runId, agentService.execute(request));
        } catch (AgentServiceException exception) {
            log.atWarn()
                    .addKeyValue("run_id", runId)
                    .addKeyValue("error_type", exception.getCause() == null
                            ? exception.getClass().getSimpleName()
                            : exception.getCause().getClass().getSimpleName())
                    .log("agent_service_run_failed");
            String code = exception.getErrorCode() == null ? "AGENT_SERVICE_ERROR" : exception.getErrorCode();
            if (exception.isTimeout() || "MODEL_TIMEOUT".equals(code)) {
                try {
                    agentService.cancel(runId, prepared.traceId());
                } catch (Exception cancelError) {
                    log.debug("Remote cancellation after timeout failed", cancelError);
                }
                runs.fail(runId, RunStatus.TIMED_OUT, code, "模型响应超时，请稍后重试");
            } else {
                runs.fail(runId, RunStatus.FAILED, code, safeMessage(code));
            }
        } catch (Exception exception) {
            log.error("Unexpected agent run failure", exception);
            runs.fail(runId, RunStatus.FAILED, "RUN_EXECUTION_ERROR", "Agent 任务执行失败，请稍后重试");
        } finally {
            if (heartbeat != null) {
                heartbeat.cancel(false);
            }
            MDC.remove("trace_id");
        }
    }

    private ScheduledFuture<?> startHeartbeat(UUID runId) {
        try {
            return scheduler.scheduleAtFixedRate(
                    () -> renewLease(runId),
                    properties.getAgent().getHeartbeatInterval());
        } catch (RuntimeException exception) {
            log.atWarn().addKeyValue("run_id", runId).log("agent_run_heartbeat_start_failed", exception);
            return null;
        }
    }

    private void renewLease(UUID runId) {
        try {
            runs.heartbeat(runId, workerId);
        } catch (RuntimeException exception) {
            log.atWarn().addKeyValue("run_id", runId).log("agent_run_heartbeat_failed", exception);
        }
    }

    private String safeMessage(String code) {
        return switch (code) {
            case "MODEL_AUTHENTICATION_FAILED" -> "模型 API Key 无效，请联系管理员检查设置";
            case "MODEL_QUOTA_EXCEEDED" -> "模型账户额度不足，请联系管理员";
            case "MODEL_RATE_LIMITED" -> "模型请求过于频繁，请稍后重试";
            case "MODEL_TIMEOUT" -> "模型响应超时，请稍后重试";
            case "RUN_CANCELLED" -> "Agent 任务已取消";
            default -> "Agent 服务暂时不可用，请稍后重试";
        };
    }
}
