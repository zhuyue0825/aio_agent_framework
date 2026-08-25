package com.aioagent.business.run;

import com.aioagent.business.agent.AgentServiceClient;
import com.aioagent.business.agent.ModelOptionsService;
import com.aioagent.business.auth.UserAccount;
import com.aioagent.business.auth.UserRepository;
import com.aioagent.business.common.ApiException;
import com.aioagent.business.conversation.Conversation;
import com.aioagent.business.conversation.ConversationMode;
import com.aioagent.business.conversation.ConversationModelProvider;
import com.aioagent.business.conversation.ConversationService;
import com.aioagent.business.conversation.Message;
import com.aioagent.business.conversation.MessageRepository;
import com.aioagent.business.conversation.MessageRole;
import com.aioagent.business.project.Project;
import com.aioagent.business.project.ProjectService;
import com.aioagent.business.config.AppProperties;
import com.aioagent.business.security.RateLimitService;
import java.time.Duration;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.data.domain.PageRequest;
import tools.jackson.core.JacksonException;
import tools.jackson.databind.ObjectMapper;

@Service
public class AgentRunService {

    private static final List<RunStatus> ACTIVE_STATUSES = List.of(RunStatus.PENDING, RunStatus.RUNNING);
    private final AgentRunRepository runs;
    private final UserRepository users;
    private final MessageRepository messages;
    private final ConversationService conversationService;
    private final ProjectService projectService;
    private final RunEventService eventService;
    private final RunEventRepository runEvents;
    private final AgentRunMetrics metrics;
    private final ObjectMapper mapper;
    private final AppProperties properties;
    private final RateLimitService rateLimits;
    private final ModelOptionsService modelOptions;
    private final TransactionTemplate transaction;

    public AgentRunService(
            AgentRunRepository runs,
            UserRepository users,
            MessageRepository messages,
            ConversationService conversationService,
            ProjectService projectService,
            RunEventService eventService,
            RunEventRepository runEvents,
            AgentRunMetrics metrics,
            AppProperties properties,
            RateLimitService rateLimits,
            ModelOptionsService modelOptions,
            TransactionTemplate transaction,
            ObjectMapper mapper) {
        this.runs = runs;
        this.users = users;
        this.messages = messages;
        this.conversationService = conversationService;
        this.projectService = projectService;
        this.eventService = eventService;
        this.runEvents = runEvents;
        this.metrics = metrics;
        this.properties = properties;
        this.rateLimits = rateLimits;
        this.modelOptions = modelOptions;
        this.transaction = transaction;
        this.mapper = mapper;
    }

    public CreateResult create(
            UserAccount user,
            UUID conversationId,
            String task,
            ConversationMode mode,
            UUID projectId,
            String approvalMode,
            int maxHistoryMessages,
            String idempotencyKey,
            String traceId) {
        Optional<AgentRun> existing = runs.findByRequestedByIdAndIdempotencyKey(user.getId(), idempotencyKey);
        if (existing.isPresent()) {
            return new CreateResult(existing.get(), false);
        }
        rateLimits.require(
                "agent-run:" + user.getId(),
                properties.getSecurity().getRunsPerMinute(),
                Duration.ofMinutes(1));
        Conversation selectedConversation = conversationService.require(user, conversationId);
        ConversationModelProvider expectedProvider = selectedConversation.getModelProvider();
        String expectedModelId = selectedConversation.getModelId();
        modelOptions.requireSelectable(user, expectedModelId);
        CreateResult result = transaction.execute(status -> createTransactional(
                user,
                conversationId,
                task,
                mode,
                projectId,
                approvalMode,
                maxHistoryMessages,
                idempotencyKey,
                traceId,
                expectedProvider,
                expectedModelId));
        if (result == null) {
            throw new IllegalStateException("Run creation transaction returned no result");
        }
        return result;
    }

    private CreateResult createTransactional(
            UserAccount user,
            UUID conversationId,
            String task,
            ConversationMode mode,
            UUID projectId,
            String approvalMode,
            int maxHistoryMessages,
            String idempotencyKey,
            String traceId,
            ConversationModelProvider expectedProvider,
            String expectedModelId) {
        UserAccount managedUser = users.findLockedById(user.getId())
                .orElseThrow(() -> new ApiException(HttpStatus.UNAUTHORIZED, "USER_NOT_FOUND", "当前用户不存在"));
        Optional<AgentRun> existing = runs.findByRequestedByIdAndIdempotencyKey(managedUser.getId(), idempotencyKey);
        if (existing.isPresent()) {
            return new CreateResult(existing.get(), false);
        }
        long dailyLimit = properties.getSecurity().getDailyTokenLimit();
        if (dailyLimit > 0) {
            Instant dayStart = Instant.now().truncatedTo(ChronoUnit.DAYS);
            long used = runs.sumTokensSince(managedUser.getId(), dayStart);
            if (used >= dailyLimit) {
                throw new ApiException(HttpStatus.TOO_MANY_REQUESTS, "TOKEN_QUOTA_EXCEEDED", "今日模型额度已用完");
            }
        }
        Conversation conversation = conversationService.requireLocked(managedUser, conversationId);
        if (conversation.getModelProvider() != expectedProvider
                || !conversation.getModelId().equals(expectedModelId)) {
            throw new ApiException(HttpStatus.CONFLICT, "MODEL_SELECTION_CHANGED", "对话模型刚刚发生变化，请重新发送");
        }
        if (runs.existsByConversationIdAndStatusIn(conversationId, ACTIVE_STATUSES)) {
            throw new ApiException(HttpStatus.CONFLICT, "RUN_ALREADY_ACTIVE", "该会话已有运行中的任务");
        }
        modelOptions.consumeRun(managedUser, conversation.getModelProvider());

        Project project = null;
        if (mode == ConversationMode.PROJECT) {
            if (projectId == null) {
                throw new ApiException(HttpStatus.BAD_REQUEST, "PROJECT_REQUIRED", "项目模式必须指定项目");
            }
            project = projectService.requireMember(projectId, managedUser);
            conversation.bindProject(project);
        } else {
            conversation.touch();
        }
        if ("新对话".equals(conversation.getTitle())) {
            String title = task.strip().replace('\n', ' ');
            conversation.rename(title.substring(0, Math.min(title.length(), 40)));
        }

        Message userMessage = messages.save(new Message(conversation, MessageRole.USER, task, "{}"));
        AgentRun run = runs.save(new AgentRun(
                conversation,
                userMessage,
                project,
                managedUser,
                task,
                mode,
                conversation.getModelProvider().apiValue(),
                conversation.getModelId(),
                approvalMode,
                maxHistoryMessages,
                idempotencyKey,
                traceId));
        eventService.append(run, "run.created", Map.of("status", run.getStatus().name()));
        return new CreateResult(run, true);
    }

    @Transactional
    public boolean claimDispatch(UUID runId, String dispatchToken) {
        Instant now = Instant.now();
        return runs.claimDispatch(
                runId,
                RunStatus.PENDING,
                dispatchToken,
                now,
                now.plus(properties.getAgent().getDispatchLease())) == 1;
    }

    @Transactional
    public void releaseDispatch(UUID runId, String dispatchToken) {
        runs.releaseDispatch(runId, RunStatus.PENDING, dispatchToken);
    }

    @Transactional
    public Optional<PreparedExecution> prepare(UUID runId, String dispatchToken, String workerId) {
        AgentRun run = runs.findLockedById(runId).orElse(null);
        if (run == null
                || run.getStatus() != RunStatus.PENDING
                || !java.util.Objects.equals(run.getDispatchToken(), dispatchToken)) {
            return Optional.empty();
        }
        run.markRunning(
                dispatchToken,
                workerId,
                Instant.now().plus(properties.getAgent().getRecoveryStaleAfter()));
        eventService.append(run, "run.started", Map.of("status", run.getStatus().name()));
        List<AgentServiceClient.HistoryMessage> history = buildHistory(run);
        return Optional.of(new PreparedExecution(
                run.getId(),
                run.getTask(),
                run.getMode(),
                run.getModelProvider(),
                run.getModelId(),
                history,
                run.getProject() == null ? null : run.getProject().getWorkspaceRoot(),
                run.getApprovalMode(),
                8,
                run.getRequestedBy().getId(),
                run.getProject() == null ? run.getRequestedBy().getId() : run.getProject().getOwner().getId(),
                run.getTraceId()));
    }

    @Transactional
    public void complete(UUID runId, AgentServiceClient.ExecutionResponse response) {
        AgentRun run = runs.findLockedById(runId).orElseThrow();
        if (run.getStatus() != RunStatus.RUNNING) {
            return;
        }
        List<String> changedFiles = response.changedFiles() == null ? List.of() : response.changedFiles();
        String changedJson = toJson(changedFiles);
        List<Map<String, Object>> proposedChanges = response.proposedChanges() == null
                ? List.of()
                : response.proposedChanges();
        run.markSucceeded(
                response.finalAnswer(),
                response.steps(),
                changedJson,
                toJson(proposedChanges),
                response.modelProvider(),
                response.modelName(),
                response.modelRequestCount(),
                response.inputTokens(),
                response.outputTokens(),
                response.modelLatencyMs());

        Map<String, Object> metadata = new LinkedHashMap<>();
        metadata.put("steps", response.steps());
        metadata.put("mode", run.getMode().name().toLowerCase());
        metadata.put("changed_files", changedFiles);
        metadata.put("proposed_change_count", proposedChanges.size());
        metadata.put("run_id", run.getId());
        metadata.put("trace_id", run.getTraceId());
        metadata.put("model_provider", response.modelProvider());
        metadata.put("model_id", run.getModelId());
        metadata.put("model_name", response.modelName());
        metadata.put("model_request_count", response.modelRequestCount());
        if (response.inputTokens() != null) {
            metadata.put("input_tokens", response.inputTokens());
        }
        if (response.outputTokens() != null) {
            metadata.put("output_tokens", response.outputTokens());
        }
        metadata.put("model_latency_ms", response.modelLatencyMs());
        if (run.getProject() != null) {
            metadata.put("project_id", run.getProject().getId());
        }
        messages.save(new Message(
                run.getConversation(),
                MessageRole.ASSISTANT,
                response.finalAnswer() == null ? "" : response.finalAnswer(),
                toJson(metadata)));
        conversationService.lock(run.getConversation().getId()).touch();
        eventService.append(run, "run.succeeded", Map.of(
                "status", run.getStatus().name(),
                "steps", response.steps(),
                "model_name", response.modelName() == null ? "unknown" : response.modelName(),
                "model_latency_ms", response.modelLatencyMs(),
                "proposed_change_count", proposedChanges.size(),
                "changed_files", changedFiles));
        metrics.completed(run);
    }

    @Transactional
    public boolean fail(UUID runId, RunStatus status, String code, String message) {
        AgentRun run = runs.findLockedById(runId).orElse(null);
        if (run == null || run.getStatus().isTerminal()) {
            return false;
        }
        failLocked(run, status, code, message);
        return true;
    }

    @Transactional
    public boolean expireStaleRun(UUID runId, Instant now) {
        AgentRun run = runs.findLockedById(runId).orElse(null);
        if (run == null
                || run.getStatus() != RunStatus.RUNNING
                || run.getLeaseExpiresAt() == null
                || !run.getLeaseExpiresAt().isBefore(now)) {
            return false;
        }
        failLocked(run, RunStatus.FAILED, "RUN_INTERRUPTED", "服务重启或任务执行中断，请重新发送");
        return true;
    }

    @Transactional
    public boolean heartbeat(UUID runId, String workerId) {
        AgentRun run = runs.findLockedById(runId).orElse(null);
        if (run == null
                || run.getStatus() != RunStatus.RUNNING
                || !java.util.Objects.equals(run.getWorkerId(), workerId)) {
            return false;
        }
        run.heartbeat(Instant.now().plus(properties.getAgent().getRecoveryStaleAfter()));
        return true;
    }

    private void failLocked(AgentRun run, RunStatus status, String code, String message) {
        String safeMessage = message == null || message.isBlank() ? "Agent 任务执行失败" : message;
        run.markFailed(status, code, safeMessage);
        messages.save(new Message(
                run.getConversation(),
                MessageRole.ERROR,
                safeMessage,
                toJson(Map.of("run_id", run.getId(), "error_code", code, "trace_id", run.getTraceId()))));
        conversationService.lock(run.getConversation().getId()).touch();
        String eventType = status == RunStatus.TIMED_OUT ? "run.timed_out" : "run.failed";
        eventService.append(run, eventType, Map.of("status", status.name(), "error_code", code, "message", safeMessage));
        metrics.terminal(run);
    }

    @Transactional
    public AgentRun cancel(UserAccount user, UUID runId) {
        AgentRun run = runs.findLockedByIdAndRequestedById(runId, user.getId())
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "RUN_NOT_FOUND", "运行任务不存在"));
        if (!run.getStatus().isTerminal()) {
            run.cancel();
            eventService.append(run, "run.cancelled", Map.of("status", run.getStatus().name()));
            metrics.terminal(run);
        }
        return run;
    }

    @Transactional
    public ChangeApplyClaim claimProposedChanges(UserAccount user, UUID runId) {
        AgentRun run = runs.findLockedByIdAndRequestedById(runId, user.getId())
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "RUN_NOT_FOUND", "运行任务不存在"));
        if ("APPLIED".equals(run.getChangeStatus())) {
            return ChangeApplyClaim.alreadyApplied(run.getId());
        }
        if ("APPLYING".equals(run.getChangeStatus())) {
            throw new ApiException(HttpStatus.CONFLICT, "CHANGES_ALREADY_APPLYING", "修改正在写入，请勿重复提交");
        }
        if (run.getProject() == null
                || (!"PROPOSED".equals(run.getChangeStatus()) && !"APPLY_FAILED".equals(run.getChangeStatus()))) {
            throw new ApiException(HttpStatus.CONFLICT, "NO_PROPOSED_CHANGES", "该任务没有待确认修改");
        }
        List<Map<String, Object>> proposed = parseProposedChanges(run.getProposedChangesJson());
        run.markChangesApplying();
        eventService.append(run, "run.changes.applying", Map.of("change_status", run.getChangeStatus()));
        return new ChangeApplyClaim(
                run.getId(),
                run.getProject().getWorkspaceRoot(),
                proposed,
                run.getProject().getOwner().getId(),
                false);
    }

    @Transactional
    public AgentRun completeProposedChanges(UUID runId, List<String> changedFiles) {
        AgentRun run = runs.findLockedById(runId)
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "RUN_NOT_FOUND", "运行任务不存在"));
        if ("APPLIED".equals(run.getChangeStatus())) {
            return run;
        }
        run.markChangesApplied(toJson(changedFiles));
        eventService.append(run, "run.changes.applied", Map.of("changed_files", changedFiles));
        return run;
    }

    @Transactional
    public void failProposedChanges(UUID runId, String message) {
        AgentRun run = runs.findLockedById(runId).orElse(null);
        if (run == null || !"APPLYING".equals(run.getChangeStatus())) {
            return;
        }
        String safeMessage = message == null || message.isBlank() ? "修改写入失败，请重试" : message;
        run.markChangesApplyFailed(safeMessage);
        eventService.append(run, "run.changes.apply_failed", Map.of("message", safeMessage));
    }

    @Transactional
    public boolean expireStaleChangeApply(UUID runId, Instant cutoff) {
        AgentRun run = runs.findLockedById(runId).orElse(null);
        if (run == null
                || !"APPLYING".equals(run.getChangeStatus())
                || run.getChangeApplyStartedAt() == null
                || !run.getChangeApplyStartedAt().isBefore(cutoff)) {
            return false;
        }
        run.markChangesApplyFailed("修改写入进程已中断，请重新确认");
        eventService.append(run, "run.changes.apply_failed", Map.of("message", run.getChangeErrorMessage()));
        return true;
    }

    @Transactional
    public AgentRun rejectProposedChanges(UserAccount user, UUID runId) {
        AgentRun run = runs.findLockedByIdAndRequestedById(runId, user.getId())
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "RUN_NOT_FOUND", "运行任务不存在"));
        if (!"PROPOSED".equals(run.getChangeStatus()) && !"APPLY_FAILED".equals(run.getChangeStatus())) {
            throw new ApiException(HttpStatus.CONFLICT, "NO_PROPOSED_CHANGES", "该任务没有待确认修改");
        }
        run.rejectChanges();
        eventService.append(run, "run.changes.rejected", Map.of());
        return run;
    }

    @Transactional
    public void recordAgentEvent(UUID runId, String eventType, Map<String, Object> payload) {
        AgentRun run = runs.findLockedById(runId)
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "RUN_NOT_FOUND", "运行任务不存在"));
        if (!run.getStatus().isTerminal()) {
            run.heartbeat(Instant.now().plus(properties.getAgent().getRecoveryStaleAfter()));
            String normalized = eventType == null ? "agent.progress" : eventType.substring(0, Math.min(eventType.length(), 80));
            eventService.append(run, normalized, payload == null ? Map.of() : payload);
        }
    }

    @Transactional(readOnly = true)
    public AgentRun require(UserAccount user, UUID runId) {
        return runs.findByIdAndRequestedById(runId, user.getId())
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "RUN_NOT_FOUND", "运行任务不存在"));
    }

    @Transactional(readOnly = true)
    public List<RunEvent> listEvents(UserAccount user, UUID runId, long afterEventId, int limit) {
        require(user, runId);
        return runEvents.findAllByRunIdAndIdGreaterThanOrderByIdAsc(
                runId,
                Math.max(0L, afterEventId),
                PageRequest.of(0, limit));
    }

    private List<AgentServiceClient.HistoryMessage> buildHistory(AgentRun run) {
        if (run.getMaxHistoryMessages() <= 0) {
            return List.of();
        }
        List<AgentServiceClient.HistoryMessage> result = new ArrayList<>();
        List<Message> recent = new ArrayList<>(messages.findAllByConversationIdOrderByCreatedAtDescIdDesc(
                run.getConversation().getId(),
                PageRequest.of(0, Math.min(100, run.getMaxHistoryMessages() + 5))).getContent());
        java.util.Collections.reverse(recent);
        for (Message message : recent) {
            if (message.getId().equals(run.getUserMessage().getId()) || message.getRole() == MessageRole.ERROR) {
                continue;
            }
            result.add(new AgentServiceClient.HistoryMessage(
                    message.getRole().name().toLowerCase(),
                    message.getContent()));
        }
        int from = Math.max(0, result.size() - run.getMaxHistoryMessages());
        return List.copyOf(result.subList(from, result.size()));
    }

    private String toJson(Object value) {
        try {
            return mapper.writeValueAsString(value);
        } catch (JacksonException exception) {
            throw new IllegalStateException("Failed to encode run metadata", exception);
        }
    }

    @SuppressWarnings("unchecked")
    private List<Map<String, Object>> parseProposedChanges(String json) {
        try {
            return mapper.readValue(json, List.class).stream()
                    .filter(Map.class::isInstance)
                    .map(value -> (Map<String, Object>) value)
                    .toList();
        } catch (JacksonException exception) {
            throw new IllegalStateException("Failed to decode proposed changes", exception);
        }
    }

    public record CreateResult(AgentRun run, boolean created) {
    }

    public record PreparedExecution(
            UUID runId,
            String task,
            ConversationMode mode,
            String modelProvider,
            String modelId,
            List<AgentServiceClient.HistoryMessage> history,
            String workspaceRoot,
            String approvalMode,
            int maxSteps,
            UUID requestedById,
            UUID workspaceOwnerId,
            String traceId) {
    }

    public record ChangeApplyClaim(
            UUID runId,
            String workspaceRoot,
            List<Map<String, Object>> proposedChanges,
            UUID workspaceOwnerId,
            boolean alreadyApplied) {
        private static ChangeApplyClaim alreadyApplied(UUID runId) {
            return new ChangeApplyClaim(runId, null, List.of(), null, true);
        }
    }
}
