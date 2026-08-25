package com.aioagent.business.agent;

import com.aioagent.business.auth.UserAccount;
import com.aioagent.business.common.ApiException;
import com.aioagent.business.conversation.ConversationModelProvider;
import com.aioagent.business.security.DeepSeekQuotaService;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;

@Service
public class ModelOptionsService {

    public static final String DEFAULT_LOCAL_MODEL_ID = ConversationModelProvider.LOCAL.defaultModelId();
    public static final String DEFAULT_REMOTE_MODEL_ID = ConversationModelProvider.REMOTE.defaultModelId();

    private final AgentServiceClient agentService;
    private final DeepSeekQuotaService quotas;

    public ModelOptionsService(AgentServiceClient agentService, DeepSeekQuotaService quotas) {
        this.agentService = agentService;
        this.quotas = quotas;
    }

    public Response options(UserAccount user) {
        DeepSeekQuotaService.Snapshot quota = quotas.snapshot(user.getId());
        boolean remoteQuotaAvailable = quota.remaining() == null || quota.remaining() > 0;
        List<Option> models = configuredOptions();
        List<Option> adjusted = models.stream().map(option -> {
            if (!"remote".equals(option.provider()) || !option.available() || remoteQuotaAvailable) {
                return option;
            }
            return new Option(
                    option.id(),
                    option.provider(),
                    option.displayName(),
                    option.modelName(),
                    option.source(),
                    false,
                    option.installed(),
                    "今日额度已用完",
                    option.architecture());
        }).toList();
        return new Response(adjusted, quota);
    }

    public Selection requireSelectable(UserAccount user, String modelId) {
        Option option = configuredOptions().stream()
                .filter(candidate -> candidate.id().equals(modelId))
                .findFirst()
                .orElseThrow(() -> new ApiException(
                        HttpStatus.CONFLICT,
                        "MODEL_NOT_FOUND",
                        "所选模型不存在，请刷新模型列表后重试"));
        if (!option.available()) {
            throw new ApiException(
                    HttpStatus.CONFLICT,
                    "MODEL_UNAVAILABLE",
                    option.unavailableReason() == null ? "所选模型当前不可用" : option.unavailableReason());
        }
        ConversationModelProvider provider = ConversationModelProvider.parse(option.provider());
        if (provider == ConversationModelProvider.REMOTE) {
            quotas.requireAvailable(user.getId());
        }
        return new Selection(option.id(), provider, option.displayName());
    }

    public Selection resolveRequested(UserAccount user, String modelId, String providerFallback) {
        String selected = modelId;
        if (selected == null || selected.isBlank()) {
            ConversationModelProvider provider = ConversationModelProvider.parse(providerFallback);
            selected = defaultModelId(provider);
        }
        return requireSelectable(user, selected);
    }

    public void consumeRun(UserAccount user, ConversationModelProvider provider) {
        if (provider != ConversationModelProvider.REMOTE) {
            return;
        }
        quotas.consume(user.getId());
    }

    public String defaultModelId(ConversationModelProvider provider) {
        return provider == ConversationModelProvider.REMOTE ? DEFAULT_REMOTE_MODEL_ID : DEFAULT_LOCAL_MODEL_ID;
    }

    private List<Option> configuredOptions() {
        List<Option> models = registryOptions();
        return models.isEmpty() ? legacyOptions() : models;
    }

    private List<Option> registryOptions() {
        Map<String, Object> registry = agentService.registeredModels();
        Object rawModels = registry == null ? null : registry.get("models");
        if (!(rawModels instanceof List<?> values)) {
            return List.of();
        }
        List<Option> result = new ArrayList<>();
        for (Object raw : values) {
            Map<?, ?> value = map(raw);
            String id = text(value.get("id"), null);
            String provider = text(value.get("provider"), null);
            String modelName = text(value.get("model_name"), null);
            if (id == null || modelName == null || !("local".equals(provider) || "remote".equals(provider))) {
                continue;
            }
            result.add(new Option(
                    id,
                    provider,
                    text(value.get("display_name"), modelName),
                    modelName,
                    text(value.get("source"), "registry"),
                    Boolean.TRUE.equals(value.get("available")),
                    Boolean.TRUE.equals(value.get("installed")),
                    text(value.get("unavailable_reason"), null),
                    text(value.get("architecture"), null)));
        }
        return List.copyOf(result);
    }

    private List<Option> legacyOptions() {
        Map<String, Object> settings = agentService.modelSettings();
        Map<?, ?> local = map(settings == null ? null : settings.get("local"));
        Map<?, ?> remote = map(settings == null ? null : settings.get("remote"));
        boolean remoteConfigured = Boolean.TRUE.equals(remote.get("api_key_configured"));
        return List.of(
                new Option(
                        DEFAULT_LOCAL_MODEL_ID,
                        "local",
                        "MiniMind 64M",
                        text(local.get("model_name"), "minimind"),
                        "configured",
                        true,
                        true,
                        null,
                        null),
                new Option(
                        DEFAULT_REMOTE_MODEL_ID,
                        "remote",
                        "DeepSeek",
                        text(remote.get("model_name"), "deepseek"),
                        "configured",
                        remoteConfigured,
                        true,
                        remoteConfigured ? null : "管理员尚未配置 API Key",
                        null));
    }

    private Map<?, ?> map(Object value) {
        return value instanceof Map<?, ?> result ? result : Map.of();
    }

    private String text(Object value, String fallback) {
        return value instanceof String text && !text.isBlank() ? text : fallback;
    }

    public record Response(List<Option> models, DeepSeekQuotaService.Snapshot deepseekQuota) {
    }

    public record Option(
            String id,
            String provider,
            String displayName,
            String modelName,
            String source,
            boolean available,
            boolean installed,
            String unavailableReason,
            String architecture) {
    }

    public record Selection(String modelId, ConversationModelProvider provider, String displayName) {
    }
}
