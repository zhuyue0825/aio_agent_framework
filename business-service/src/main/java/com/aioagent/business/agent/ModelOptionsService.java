package com.aioagent.business.agent;

import com.aioagent.business.auth.UserAccount;
import com.aioagent.business.common.ApiException;
import com.aioagent.business.conversation.ConversationModelProvider;
import com.aioagent.business.security.DeepSeekQuotaService;
import java.util.List;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;

@Service
public class ModelOptionsService {

    private final AgentServiceClient agentService;
    private final DeepSeekQuotaService quotas;

    public ModelOptionsService(AgentServiceClient agentService, DeepSeekQuotaService quotas) {
        this.agentService = agentService;
        this.quotas = quotas;
    }

    public Response options(UserAccount user) {
        Map<String, Object> settings = agentService.modelSettings();
        Map<?, ?> local = map(settings.get("local"));
        Map<?, ?> remote = map(settings.get("remote"));
        DeepSeekQuotaService.Snapshot quota = quotas.snapshot(user.getId());
        boolean remoteConfigured = Boolean.TRUE.equals(remote.get("api_key_configured"));
        boolean remoteQuotaAvailable = quota.remaining() == null || quota.remaining() > 0;
        return new Response(
                List.of(
                        new Option("local", "MiniMind", text(local.get("model_name"), "minimind"), true, null),
                        new Option(
                                "remote",
                                "DeepSeek",
                                text(remote.get("model_name"), "deepseek"),
                                remoteConfigured && remoteQuotaAvailable,
                                remoteConfigured ? (remoteQuotaAvailable ? null : "今日额度已用完") : "管理员尚未配置 API Key")),
                quota);
    }

    public void requireSelectable(UserAccount user, ConversationModelProvider provider) {
        if (provider != ConversationModelProvider.REMOTE) {
            return;
        }
        requireConfigured(provider);
        quotas.requireAvailable(user.getId());
    }

    public void requireConfigured(ConversationModelProvider provider) {
        if (provider != ConversationModelProvider.REMOTE) {
            return;
        }
        requireRemoteConfigured();
    }

    public void consumeRun(UserAccount user, ConversationModelProvider provider) {
        if (provider != ConversationModelProvider.REMOTE) {
            return;
        }
        quotas.consume(user.getId());
    }

    private void requireRemoteConfigured() {
        Map<?, ?> remote = map(agentService.modelSettings().get("remote"));
        if (!Boolean.TRUE.equals(remote.get("api_key_configured"))) {
            throw new ApiException(
                    HttpStatus.CONFLICT,
                    "DEEPSEEK_NOT_CONFIGURED",
                    "管理员尚未配置 DeepSeek API Key");
        }
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
            String provider,
            String displayName,
            String modelName,
            boolean available,
            String unavailableReason) {
    }
}
