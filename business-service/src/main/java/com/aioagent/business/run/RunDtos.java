package com.aioagent.business.run;

import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import tools.jackson.core.JacksonException;
import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.ObjectMapper;

public final class RunDtos {

    private static final TypeReference<List<String>> STRING_LIST = new TypeReference<>() {
    };
    private static final TypeReference<Map<String, Object>> MAP_TYPE = new TypeReference<>() {
    };
    private static final TypeReference<List<Map<String, Object>>> MAP_LIST = new TypeReference<>() {
    };

    private RunDtos() {
    }

    public record RunResponse(
            UUID id,
            UUID conversationId,
            UUID projectId,
            RunStatus status,
            String task,
            String mode,
            String traceId,
            String finalAnswer,
            Integer steps,
            String modelProvider,
            String modelName,
            int modelRequestCount,
            Long inputTokens,
            Long outputTokens,
            long modelLatencyMs,
            int attemptCount,
            List<String> changedFiles,
            List<Map<String, Object>> proposedChanges,
            String changeStatus,
            Instant changesAppliedAt,
            String errorCode,
            String errorMessage,
            Instant createdAt,
            Instant startedAt,
            Instant finishedAt) {
        public static RunResponse from(AgentRun run, ObjectMapper mapper) {
            return new RunResponse(
                    run.getId(),
                    run.getConversation().getId(),
                    run.getProject() == null ? null : run.getProject().getId(),
                    run.getStatus(),
                    run.getTask(),
                    run.getMode().name().toLowerCase(),
                    run.getTraceId(),
                    run.getFinalAnswer(),
                    run.getSteps(),
                    run.getModelProvider(),
                    run.getModelName(),
                    run.getModelRequestCount(),
                    run.getInputTokens(),
                    run.getOutputTokens(),
                    run.getModelLatencyMs(),
                    run.getAttemptCount(),
                    parseList(run.getChangedFilesJson(), mapper),
                    parseMapList(run.getProposedChangesJson(), mapper),
                    run.getChangeStatus(),
                    run.getChangesAppliedAt(),
                    run.getErrorCode(),
                    run.getErrorMessage(),
                    run.getCreatedAt(),
                    run.getStartedAt(),
                    run.getFinishedAt());
        }
    }

    public record RunEventResponse(
            long id,
            UUID runId,
            String eventType,
            Map<String, Object> payload,
            Instant createdAt) {
        public static RunEventResponse from(RunEvent event, ObjectMapper mapper) {
            return new RunEventResponse(
                    event.getId(),
                    event.getRun().getId(),
                    event.getEventType(),
                    parseMap(event.getPayloadJson(), mapper),
                    event.getCreatedAt());
        }
    }

    private static List<String> parseList(String json, ObjectMapper mapper) {
        try {
            return mapper.readValue(json, STRING_LIST);
        } catch (JacksonException exception) {
            return List.of();
        }
    }

    private static Map<String, Object> parseMap(String json, ObjectMapper mapper) {
        try {
            return mapper.readValue(json, MAP_TYPE);
        } catch (JacksonException exception) {
            return Map.of();
        }
    }

    private static List<Map<String, Object>> parseMapList(String json, ObjectMapper mapper) {
        try {
            return mapper.readValue(json, MAP_LIST);
        } catch (JacksonException exception) {
            return List.of();
        }
    }
}
