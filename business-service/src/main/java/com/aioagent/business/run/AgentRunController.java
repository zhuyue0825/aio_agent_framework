package com.aioagent.business.run;

import com.aioagent.business.agent.AgentServiceClient;
import com.aioagent.business.auth.CurrentUser;
import com.aioagent.business.auth.UserAccount;
import com.aioagent.business.common.TraceIdFilter;
import com.aioagent.business.conversation.ConversationMode;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import java.net.URI;
import java.util.Map;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;
import tools.jackson.databind.ObjectMapper;

@RestController
@RequestMapping("/api/v1")
@Validated
public class AgentRunController {

    private final CurrentUser currentUser;
    private final AgentRunService runs;
    private final AgentRunExecutor executor;
    private final AgentServiceClient agentService;
    private final SseRunEventHub eventHub;
    private final ObjectMapper mapper;

    public AgentRunController(
            CurrentUser currentUser,
            AgentRunService runs,
            AgentRunExecutor executor,
            AgentServiceClient agentService,
            SseRunEventHub eventHub,
            ObjectMapper mapper) {
        this.currentUser = currentUser;
        this.runs = runs;
        this.executor = executor;
        this.agentService = agentService;
        this.eventHub = eventHub;
        this.mapper = mapper;
    }

    @PostMapping("/conversations/{conversationId}/runs")
    public ResponseEntity<Map<String, RunDtos.RunResponse>> create(
            @PathVariable UUID conversationId,
            @RequestHeader("Idempotency-Key") @Size(min = 8, max = 100) String idempotencyKey,
            @Valid @RequestBody CreateRunRequest request,
            Authentication authentication,
            HttpServletRequest servletRequest) {
        UserAccount user = currentUser.require(authentication);
        String traceId = String.valueOf(servletRequest.getAttribute(TraceIdFilter.REQUEST_ATTRIBUTE));
        AgentRunService.CreateResult result = runs.create(
                user,
                conversationId,
                request.task(),
                parseMode(request.mode()),
                request.projectId(),
                request.approvalMode(),
                request.maxHistoryMessages(),
                idempotencyKey,
                traceId);
        if (result.created()) {
            executor.execute(result.run().getId());
        }
        RunDtos.RunResponse response = RunDtos.RunResponse.from(result.run(), mapper);
        if (!result.created()) {
            return ResponseEntity.ok(Map.of("run", response));
        }
        return ResponseEntity.status(HttpStatus.ACCEPTED)
                .location(URI.create("/api/v1/runs/" + result.run().getId()))
                .body(Map.of("run", response));
    }

    @GetMapping("/runs/{runId}")
    public Map<String, RunDtos.RunResponse> get(@PathVariable UUID runId, Authentication authentication) {
        AgentRun run = runs.require(currentUser.require(authentication), runId);
        return Map.of("run", RunDtos.RunResponse.from(run, mapper));
    }

    @DeleteMapping("/runs/{runId}")
    public Map<String, RunDtos.RunResponse> cancel(@PathVariable UUID runId, Authentication authentication) {
        AgentRun run = runs.cancel(currentUser.require(authentication), runId);
        if (run.getStatus() == RunStatus.CANCELLED) {
            try {
                agentService.cancel(runId, run.getTraceId());
            } catch (Exception ignored) {
                // Local cancellation is authoritative; the remote run also checks its cooperative flag.
            }
        }
        return Map.of("run", RunDtos.RunResponse.from(run, mapper));
    }

    @GetMapping(value = "/runs/{runId}/events", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public SseEmitter events(@PathVariable UUID runId, Authentication authentication) {
        AgentRun run = runs.require(currentUser.require(authentication), runId);
        return eventHub.subscribe(run);
    }

    private ConversationMode parseMode(String value) {
        return "project".equalsIgnoreCase(value) ? ConversationMode.PROJECT : ConversationMode.CHAT;
    }

    public record CreateRunRequest(
            @NotBlank String task,
            @Size(max = 20) String mode,
            UUID projectId,
            @Size(max = 20) String approvalMode,
            @Min(0) @Max(30) int maxHistoryMessages) {
        public CreateRunRequest {
            if (mode == null) {
                mode = "chat";
            }
            if (approvalMode == null) {
                approvalMode = "auto";
            }
        }
    }
}
