package com.aioagent.business.run;

import java.util.UUID;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.scheduling.concurrent.ThreadPoolTaskExecutor;
import org.springframework.stereotype.Component;

@Component
@ConditionalOnProperty(prefix = "app.redis", name = "enabled", havingValue = "false", matchIfMissing = true)
public class LocalAgentRunDispatcher implements AgentRunDispatcher {

    private final AgentRunExecutor runner;
    private final ThreadPoolTaskExecutor taskExecutor;

    public LocalAgentRunDispatcher(AgentRunExecutor runner, ThreadPoolTaskExecutor taskExecutor) {
        this.runner = runner;
        this.taskExecutor = taskExecutor;
    }

    @Override
    public void dispatch(UUID runId) {
        taskExecutor.execute(() -> runner.execute(runId));
    }
}
