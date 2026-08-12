package com.aioagent.business.agent;

import org.springframework.boot.health.contributor.Health;
import org.springframework.boot.health.contributor.HealthIndicator;
import org.springframework.stereotype.Component;

@Component("agentService")
public class AgentServiceHealthIndicator implements HealthIndicator {

    private final AgentServiceClient agentService;

    public AgentServiceHealthIndicator(AgentServiceClient agentService) {
        this.agentService = agentService;
    }

    @Override
    public Health health() {
        try {
            AgentServiceClient.HealthResponse response = agentService.health();
            if (!response.ok()) {
                return Health.down().withDetail("service", response.service()).build();
            }
            return Health.up()
                    .withDetail("model", response.modelName())
                    .withDetail("maxSteps", response.maxSteps())
                    .build();
        } catch (Exception exception) {
            return Health.down(exception).build();
        }
    }
}
