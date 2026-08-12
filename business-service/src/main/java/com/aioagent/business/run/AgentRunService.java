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
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
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
    private final ObjectMapper mapper;

    public AgentRunService(
            AgentRunRepository runs,
            UserRepository users,
            MessageRepository messages,
            ConversationService conversationService,
            ProjectService projectService,
            RunEventService eventService,
            ObjectMapper mapper) {
        this.runs = runs;
        this.users = users;
        this.messages = messages;
        this.conversationService = conversationService;
        this.projectService = projectService;
        this.eventService = eventService;
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
        run.markSucceeded(response.finalAnswer(), response.steps(), changedJson);

        Map<String, Object> metadata = new LinkedHashMap<>();
        metadata.put("steps", response.steps());
        metadata.put("mode", run.getMode().name().toLowerCase());
        metadata.put("changed_files", changedFiles);
        metadata.put("run_id", run.getId());
        metadata.put("trace_id", run.getTraceId());
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
                "changed_files", changedFiles));
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
    }

    @Transactional
    public AgentRun cancel(UserAccount user, UUID runId) {
        AgentRun run = require(user, runId);
        if (!run.getStatus().isTerminal()) {
            run.cancel();
            eventService.append(run, "run.cancelled", Map.of("status", run.getStatus().name()));
        }
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

    private List<AgentServiceClient.HistoryMessage> buildHistory(AgentRun run) {
        if (run.getMaxHistoryMessages() <= 0) {
            return List.of();
        }
        List<AgentServiceClient.HistoryMessage> result = new ArrayList<>();
        for (Message message : messages.findAllByConversationIdOrderByCreatedAtAscIdAsc(run.getConversation().getId())) {
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
            String traceId) {
    }
}
