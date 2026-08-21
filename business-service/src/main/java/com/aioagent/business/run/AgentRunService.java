package com.aioagent.business.run;

import com.aioagent.business.agent.AgentServiceClient;
import com.aioagent.business.auth.UserAccount;
import com.aioagent.business.auth.UserRepository;
import com.aioagent.business.common.ApiException;
import com.aioagent.business.conversation.Conversation;
import com.aioagent.business.conversation.ConversationMode;
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
        this.mapper = mapper;
    }

    @Transactional
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
        users.findLockedById(user.getId())
                .orElseThrow(() -> new ApiException(HttpStatus.UNAUTHORIZED, "USER_NOT_FOUND", "当前用户不存在"));
        Optional<AgentRun> existing = runs.findByRequestedByIdAndIdempotencyKey(user.getId(), idempotencyKey);
        if (existing.isPresent()) {
            return new CreateResult(existing.get(), false);
        }
        rateLimits.require(
                "agent-run:" + user.getId(),
                properties.getSecurity().getRunsPerMinute(),
                Duration.ofMinutes(1));
        long dailyLimit = properties.getSecurity().getDailyTokenLimit();
        if (dailyLimit > 0) {
            Instant dayStart = Instant.now().truncatedTo(ChronoUnit.DAYS);
            long used = runs.sumTokensSince(user.getId(), dayStart);
            if (used >= dailyLimit) {
                throw new ApiException(HttpStatus.TOO_MANY_REQUESTS, "TOKEN_QUOTA_EXCEEDED", "今日模型额度已用完");
            }
        }
        Conversation conversation = conversationService.require(user, conversationId);
        if (runs.existsByConversationIdAndStatusIn(conversationId, ACTIVE_STATUSES)) {
            throw new ApiException(HttpStatus.CONFLICT, "RUN_ALREADY_ACTIVE", "该会话已有运行中的任务");
        }

        Project project = null;
        if (mode == ConversationMode.PROJECT) {
            if (projectId == null) {
                throw new ApiException(HttpStatus.BAD_REQUEST, "PROJECT_REQUIRED", "项目模式必须指定项目");
            }
            project = projectService.requireMember(projectId, user);
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
                user,
                task,
                mode,
                approvalMode,
                maxHistoryMessages,
                idempotencyKey,
                traceId));
        eventService.append(run, "run.created", Map.of("status", run.getStatus().name()));
        return new CreateResult(run, true);
    }

    @Transactional
    public Optional<PreparedExecution> prepare(UUID runId) {
        AgentRun run = runs.findById(runId).orElse(null);
        if (run == null || run.getStatus() != RunStatus.PENDING) {
            return Optional.empty();
        }
        run.markRunning();
        eventService.append(run, "run.started", Map.of("status", run.getStatus().name()));
        List<AgentServiceClient.HistoryMessage> history = buildHistory(run);
        return Optional.of(new PreparedExecution(
                run.getId(),
                run.getTask(),
                run.getMode(),
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
        AgentRun run = runs.findById(runId).orElseThrow();
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
        run.getConversation().touch();
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
    public void fail(UUID runId, RunStatus status, String code, String message) {
        AgentRun run = runs.findById(runId).orElse(null);
        if (run == null || run.getStatus().isTerminal()) {
            return;
        }
        String safeMessage = message == null || message.isBlank() ? "Agent 任务执行失败" : message;
        run.markFailed(status, code, safeMessage);
        messages.save(new Message(
                run.getConversation(),
                MessageRole.ERROR,
                safeMessage,
                toJson(Map.of("run_id", runId, "error_code", code, "trace_id", run.getTraceId()))));
        run.getConversation().touch();
        String eventType = status == RunStatus.TIMED_OUT ? "run.timed_out" : "run.failed";
        eventService.append(run, eventType, Map.of("status", status.name(), "error_code", code, "message", safeMessage));
        metrics.terminal(run);
    }

    @Transactional
    public AgentRun cancel(UserAccount user, UUID runId) {
        AgentRun run = require(user, runId);
        if (!run.getStatus().isTerminal()) {
            run.cancel();
            eventService.append(run, "run.cancelled", Map.of("status", run.getStatus().name()));
            metrics.terminal(run);
        }
        return run;
    }

    @Transactional
    public AgentRun applyProposedChanges(UserAccount user, UUID runId, AgentServiceClient agentService) {
        AgentRun run = require(user, runId);
        if (run.getProject() == null || !"PROPOSED".equals(run.getChangeStatus())) {
            throw new ApiException(HttpStatus.CONFLICT, "NO_PROPOSED_CHANGES", "该任务没有待确认修改");
        }
        List<Map<String, Object>> proposed = parseProposedChanges(run.getProposedChangesJson());
        List<String> changedFiles = agentService.applyWorkspaceChanges(
                run.getProject().getWorkspaceRoot(),
                proposed,
                run.getProject().getOwner().getId());
        run.markChangesApplied(toJson(changedFiles));
        eventService.append(run, "run.changes.applied", Map.of("changed_files", changedFiles));
        return run;
    }

    @Transactional
    public AgentRun rejectProposedChanges(UserAccount user, UUID runId) {
        AgentRun run = require(user, runId);
        if (!"PROPOSED".equals(run.getChangeStatus())) {
            throw new ApiException(HttpStatus.CONFLICT, "NO_PROPOSED_CHANGES", "该任务没有待确认修改");
        }
        run.rejectChanges();
        eventService.append(run, "run.changes.rejected", Map.of());
        return run;
    }

    @Transactional
    public void recordAgentEvent(UUID runId, String eventType, Map<String, Object> payload) {
        AgentRun run = runs.findById(runId)
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "RUN_NOT_FOUND", "运行任务不存在"));
        if (!run.getStatus().isTerminal()) {
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
            List<AgentServiceClient.HistoryMessage> history,
            String workspaceRoot,
            String approvalMode,
            int maxSteps,
            UUID requestedById,
            UUID workspaceOwnerId,
            String traceId) {
    }
}
