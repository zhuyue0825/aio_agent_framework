package com.aioagent.business;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.timeout;
import static org.mockito.Mockito.verify;

import com.aioagent.business.config.AppProperties;
import com.aioagent.business.run.AgentCancellationPublisher;
import com.aioagent.business.run.AgentRunExecutor;
import com.aioagent.business.run.RedisAgentRunDispatcher;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.connection.lettuce.LettuceConnectionFactory;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.scheduling.concurrent.ThreadPoolTaskExecutor;
import org.testcontainers.containers.GenericContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;
import org.testcontainers.utility.DockerImageName;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;

@Testcontainers
class RedisRunDispatcherIntegrationTest {

    @Container
    static final GenericContainer<?> REDIS = new GenericContainer<>(DockerImageName.parse("redis:8-alpine"))
            .withExposedPorts(6379);

    @Test
    void streamConsumerRunsAndAcknowledgesDispatchedJob() {
        LettuceConnectionFactory connectionFactory = new LettuceConnectionFactory(
                REDIS.getHost(), REDIS.getMappedPort(6379));
        connectionFactory.afterPropertiesSet();
        connectionFactory.start();
        StringRedisTemplate template = new StringRedisTemplate(connectionFactory);
        template.afterPropertiesSet();
        ThreadPoolTaskExecutor taskExecutor = new ThreadPoolTaskExecutor();
        taskExecutor.setCorePoolSize(1);
        taskExecutor.setMaxPoolSize(1);
        taskExecutor.setWaitForTasksToCompleteOnShutdown(true);
        taskExecutor.setAwaitTerminationSeconds(5);
        taskExecutor.initialize();
        AgentRunExecutor runner = mock(AgentRunExecutor.class);
        AppProperties properties = new AppProperties();
        properties.getRedis().setEnabled(true);
        properties.getRedis().setKeyPrefix("test:" + UUID.randomUUID());
        properties.getRedis().setRunStream("test:runs:" + UUID.randomUUID());
        properties.getRedis().setRunGroup("test-group");
        RedisAgentRunDispatcher dispatcher = new RedisAgentRunDispatcher(
                template,
                connectionFactory,
                runner,
                taskExecutor,
                properties,
                new SimpleMeterRegistry());
        try {
            dispatcher.start();
            UUID runId = UUID.randomUUID();
            dispatcher.dispatch(runId);
            verify(runner, timeout(5_000)).execute(runId);
            UUID cancelledRunId = UUID.randomUUID();
            new AgentCancellationPublisher(template, properties).publish(cancelledRunId);
            assertEquals(
                    "1",
                    template.opsForValue().get(
                            properties.getRedis().getKeyPrefix() + ":run-cancelled:" + cancelledRunId));
        } finally {
            dispatcher.stop();
            taskExecutor.shutdown();
            connectionFactory.destroy();
        }
    }
}
