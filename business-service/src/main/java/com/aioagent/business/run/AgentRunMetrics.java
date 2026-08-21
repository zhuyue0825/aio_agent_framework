package com.aioagent.business.run;

import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;
import java.time.Duration;
import org.springframework.stereotype.Component;

@Component
public class AgentRunMetrics {

    private final MeterRegistry registry;

    public AgentRunMetrics(MeterRegistry registry) {
        this.registry = registry;
    }

    public void completed(AgentRun run) {
        String provider = valueOrUnknown(run.getModelProvider());
        String model = valueOrUnknown(run.getModelName());
        Counter.builder("aio.agent.model.requests")
                .tag("provider", provider)
                .tag("model", model)
                .register(registry)
                .increment(run.getModelRequestCount());
        if (run.getInputTokens() != null) {
            Counter.builder("aio.agent.model.tokens")
                    .tag("direction", "input")
                    .tag("provider", provider)
                    .register(registry)
                    .increment(run.getInputTokens());
        }
        if (run.getOutputTokens() != null) {
            Counter.builder("aio.agent.model.tokens")
                    .tag("direction", "output")
                    .tag("provider", provider)
                    .register(registry)
                    .increment(run.getOutputTokens());
        }
        Timer.builder("aio.agent.model.latency")
                .tag("provider", provider)
                .tag("model", model)
                .register(registry)
                .record(Duration.ofMillis(run.getModelLatencyMs()));
        terminal(run);
    }

    public void terminal(AgentRun run) {
        Counter.builder("aio.agent.runs")
                .tag("status", run.getStatus().name().toLowerCase())
                .register(registry)
                .increment();
        if (run.getStartedAt() != null && run.getFinishedAt() != null) {
            Timer.builder("aio.agent.run.duration")
                    .tag("status", run.getStatus().name().toLowerCase())
                    .register(registry)
                    .record(Duration.between(run.getStartedAt(), run.getFinishedAt()));
        }
    }

    private String valueOrUnknown(String value) {
        return value == null || value.isBlank() ? "unknown" : value;
    }
}
