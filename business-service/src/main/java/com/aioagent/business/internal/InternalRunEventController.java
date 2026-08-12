package com.aioagent.business.internal;

import com.aioagent.business.agent.AgentServiceClient;
import com.aioagent.business.common.ApiException;
import com.aioagent.business.config.AppProperties;
import com.aioagent.business.run.AgentRunService;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Map;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/internal/v1/runs")
public class InternalRunEventController {

    private final AgentRunService runs;
    private final AppProperties properties;

    public InternalRunEventController(AgentRunService runs, AppProperties properties) {
        this.runs = runs;
        this.properties = properties;
    }

    @PostMapping("/{runId}/events")
    public Map<String, Boolean> event(
            @PathVariable UUID runId,
            @RequestHeader(AgentServiceClient.INTERNAL_TOKEN_HEADER) String internalToken,
            @RequestBody AgentEventRequest request) {
        verifyToken(internalToken);
        runs.recordAgentEvent(runId, request.eventType(), request.payload());
        return Map.of("ok", true);
    }

    private void verifyToken(String supplied) {
        byte[] expected = properties.getAgent().getInternalToken().getBytes(StandardCharsets.UTF_8);
        byte[] actual = supplied.getBytes(StandardCharsets.UTF_8);
        if (!MessageDigest.isEqual(expected, actual)) {
            throw new ApiException(HttpStatus.UNAUTHORIZED, "INVALID_INTERNAL_TOKEN", "内部服务凭证无效");
        }
    }

    public record AgentEventRequest(String eventType, Map<String, Object> payload, String traceId) {
    }
}
