package com.aioagent.business.agent;

import com.aioagent.business.common.TraceIdFilter;
import com.aioagent.business.config.AppProperties;
import com.aioagent.business.conversation.ConversationMode;
import java.net.http.HttpClient;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;
import org.slf4j.MDC;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.http.MediaType;
import org.springframework.http.client.JdkClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestClientResponseException;

@Component
public class AgentServiceClient {

    public static final String INTERNAL_TOKEN_HEADER = "X-Internal-Token";
    private static final ParameterizedTypeReference<Map<String, Object>> MAP_TYPE = new ParameterizedTypeReference<>() {
    };

    private final RestClient client;
    private final AppProperties properties;

    public AgentServiceClient(AppProperties properties, RestClient.Builder clientBuilder) {
        this.properties = properties;
        HttpClient httpClient = HttpClient.newBuilder()
                .version(HttpClient.Version.HTTP_1_1)
                .connectTimeout(properties.getAgent().getConnectTimeout())
                .build();
        JdkClientHttpRequestFactory requestFactory = new JdkClientHttpRequestFactory(httpClient);
        requestFactory.setReadTimeout(properties.getAgent().getReadTimeout());
        this.client = clientBuilder
                .baseUrl(properties.getAgent().getBaseUrl())
                .requestFactory(requestFactory)
                .defaultHeader(INTERNAL_TOKEN_HEADER, properties.getAgent().getInternalToken())
                .requestInterceptor((request, body, execution) -> {
                    String traceId = MDC.get("trace_id");
                    if (traceId != null && !traceId.isBlank()) {
                        request.getHeaders().set(TraceIdFilter.HEADER, traceId);
                    }
                    return execution.execute(request, body);
                })
                .build();
    }

    public HealthResponse health() {
        try {
            return client.get()
                    .uri("/internal/v1/health")
                    .retrieve()
                    .body(HealthResponse.class);
        } catch (RestClientException exception) {
            throw wrap("Agent service health check failed", exception);
        }
    }

    public ExecutionResponse execute(ExecutionRequest request) {
        try {
            return client.post()
                    .uri("/internal/v1/agent/runs")
                    .contentType(MediaType.APPLICATION_JSON)
                    .header("X-Trace-Id", request.traceId())
                    .body(request)
                    .retrieve()
                    .body(ExecutionResponse.class);
        } catch (RestClientException exception) {
            throw wrap("Agent execution failed", exception);
        }
    }

    public Map<String, Object> modelSettings() {
        try {
            return client.get().uri("/internal/v1/model-settings").retrieve().body(MAP_TYPE);
        } catch (RestClientException exception) {
            throw wrap("Model settings request failed", exception);
        }
    }

    public Map<String, Object> updateModelSettings(Map<String, Object> settings) {
        try {
            return client.put()
                    .uri("/internal/v1/model-settings")
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(settings)
                    .retrieve()
                    .body(MAP_TYPE);
        } catch (RestClientException exception) {
            throw wrap("Model settings update failed", exception);
        }
    }

    public Map<String, Object> testModelSettings() {
        try {
            return client.post()
                    .uri("/internal/v1/model-settings/test")
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(Map.of())
                    .retrieve()
                    .body(MAP_TYPE);
        } catch (RestClientException exception) {
            throw wrap("Model connection test failed", exception);
        }
    }

    public void cancel(UUID runId, String traceId) {
        try {
            client.delete()
                    .uri("/internal/v1/agent/runs/{runId}", runId)
                    .header("X-Trace-Id", traceId)
                    .retrieve()
                    .toBodilessEntity();
        } catch (RestClientResponseException exception) {
            if (exception.getStatusCode().value() != 404 && exception.getStatusCode().value() != 409) {
                throw wrap("Agent cancellation failed", exception);
            }
        } catch (RestClientException exception) {
            throw wrap("Agent cancellation failed", exception);
        }
    }

    public Map<String, Object> listDirectories(String path) {
        return getMap("/internal/v1/workspaces/directories", Optional.ofNullable(path), null, null);
    }

    public Map<String, Object> openWorkspace(String path) {
        return postMap("/internal/v1/workspaces/open", Map.of("path", path));
    }

    public Map<String, Object> workspaceTree(String root) {
        return getMap("/internal/v1/workspaces/tree", Optional.of(root), null, null);
    }

    public Map<String, Object> workspaceFile(String root, String relativePath) {
        return getMap("/internal/v1/workspaces/file", Optional.empty(), root, relativePath);
    }

    public Map<String, Object> saveWorkspaceFile(String root, String relativePath, String content) {
        return putMap("/internal/v1/workspaces/file", Map.of("root", root, "path", relativePath, "content", content));
    }

    private Map<String, Object> getMap(String endpoint, Optional<String> path, String root, String relativePath) {
        try {
            return client.get()
                    .uri(builder -> {
                        builder.path(endpoint);
                        path.ifPresent(value -> builder.queryParam("path", value));
                        if (root != null) {
                            builder.queryParam("root", root);
                        }
                        if (relativePath != null) {
                            builder.queryParam("path", relativePath);
                        }
                        return builder.build();
                    })
                    .retrieve()
                    .body(MAP_TYPE);
        } catch (RestClientException exception) {
            throw wrap("Workspace request failed", exception);
        }
    }

    private Map<String, Object> postMap(String endpoint, Map<String, Object> body) {
        try {
            return client.post().uri(endpoint).contentType(MediaType.APPLICATION_JSON).body(body).retrieve().body(MAP_TYPE);
        } catch (RestClientException exception) {
            throw wrap("Workspace request failed", exception);
        }
    }

    private Map<String, Object> putMap(String endpoint, Map<String, Object> body) {
        try {
            return client.put().uri(endpoint).contentType(MediaType.APPLICATION_JSON).body(body).retrieve().body(MAP_TYPE);
        } catch (RestClientException exception) {
            throw wrap("Workspace request failed", exception);
        }
    }

    private AgentServiceException wrap(String message, RestClientException exception) {
        boolean timeout = exception instanceof ResourceAccessException
                && exception.getMessage() != null
                && exception.getMessage().toLowerCase().contains("timed out");
        return new AgentServiceException(message, exception, timeout);
    }

    public String callbackUrl(UUID runId) {
        return properties.getAgent().getCallbackBaseUrl() + "/internal/v1/runs/" + runId + "/events";
    }

    public record HealthResponse(
            boolean ok,
            String service,
            String modelProvider,
            String modelName,
            String modelApiBase,
            boolean apiKeyConfigured,
            int maxSteps,
            boolean supportsProjects) {
    }

    public record HistoryMessage(String role, String content) {
    }

    public record ExecutionRequest(
            UUID runId,
            String task,
            String mode,
            List<HistoryMessage> history,
            String workspaceRoot,
            String approvalMode,
            int maxSteps,
            String traceId,
            String callbackUrl) {
    }

    public record ExecutionResponse(String finalAnswer, int steps, List<String> changedFiles, String traceId) {
    }
}
