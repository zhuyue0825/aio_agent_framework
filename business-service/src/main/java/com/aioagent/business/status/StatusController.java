package com.aioagent.business.status;

import com.aioagent.business.agent.AgentServiceClient;
import java.util.Map;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1")
public class StatusController {

    private final AgentServiceClient agentService;

    public StatusController(AgentServiceClient agentService) {
        this.agentService = agentService;
    }

    @GetMapping("/status")
    public Map<String, Object> status() {
        AgentServiceClient.HealthResponse agent = agentService.health();
        return Map.of(
                "business_service", "UP",
                "agent_service", agent.ok() ? "UP" : "DOWN",
                "model_provider", agent.modelProvider(),
                "model_name", agent.modelName(),
                "model_api_base", agent.modelApiBase(),
                "api_key_configured", agent.apiKeyConfigured(),
                "max_steps", agent.maxSteps(),
                "supports_projects", agent.supportsProjects());
    }
}
