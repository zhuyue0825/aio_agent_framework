package com.aioagent.business.agent;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;
import java.util.LinkedHashMap;
import java.util.Map;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/model-settings")
@PreAuthorize("hasRole('ADMIN')")
public class ModelSettingsController {

    private final AgentServiceClient agentService;

    public ModelSettingsController(AgentServiceClient agentService) {
        this.agentService = agentService;
    }

    @GetMapping
    public Map<String, Object> get() {
        return agentService.modelSettings();
    }

    @PutMapping
    public Map<String, Object> update(@Valid @RequestBody UpdateRequest request) {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("active_provider", request.activeProvider());
        payload.put("remote_api_base", request.remoteApiBase());
        payload.put("remote_model_name", request.remoteModelName());
        payload.put("local_api_base", request.localApiBase());
        payload.put("local_model_name", request.localModelName());
        if (request.remoteApiKey() != null && !request.remoteApiKey().isBlank()) {
            payload.put("remote_api_key", request.remoteApiKey());
        }
        return agentService.updateModelSettings(payload);
    }

    @PostMapping("/test")
    public Map<String, Object> test() {
        return agentService.testModelSettings();
    }

    public record UpdateRequest(
            @NotBlank @Pattern(regexp = "local|remote") String activeProvider,
            @NotBlank @Size(max = 2_000) @Pattern(regexp = "https?://.+") String remoteApiBase,
            @NotBlank @Size(max = 200) String remoteModelName,
            @Size(max = 2_000) String remoteApiKey,
            @NotBlank @Size(max = 2_000) @Pattern(regexp = "https?://.+") String localApiBase,
            @NotBlank @Size(max = 200) String localModelName) {
    }
}
