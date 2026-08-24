package com.aioagent.business.config;

import java.util.Map;
import org.slf4j.MDC;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.task.TaskDecorator;
import org.springframework.scheduling.concurrent.ThreadPoolTaskExecutor;
import io.micrometer.core.instrument.Gauge;
import io.micrometer.core.instrument.MeterRegistry;

@Configuration(proxyBeanMethods = false)
public class AsyncConfig {

    @Bean(name = "agentTaskExecutor")
    ThreadPoolTaskExecutor agentTaskExecutor(MeterRegistry meterRegistry) {
        ThreadPoolTaskExecutor executor = new ThreadPoolTaskExecutor();
        executor.setCorePoolSize(2);
        executor.setMaxPoolSize(4);
        executor.setQueueCapacity(100);
        executor.setThreadNamePrefix("agent-run-");
        executor.setTaskDecorator(mdcTaskDecorator());
        executor.initialize();
        Gauge.builder("aio.agent.queue.depth", executor, value -> value.getThreadPoolExecutor().getQueue().size())
                .register(meterRegistry);
        Gauge.builder("aio.agent.executor.active", executor, ThreadPoolTaskExecutor::getActiveCount)
                .register(meterRegistry);
        return executor;
    }

    private TaskDecorator mdcTaskDecorator() {
        return runnable -> {
            Map<String, String> context = MDC.getCopyOfContextMap();
            return () -> {
                if (context != null) {
                    MDC.setContextMap(context);
                }
                try {
                    runnable.run();
                } finally {
                    MDC.clear();
                }
            };
        };
    }
}
