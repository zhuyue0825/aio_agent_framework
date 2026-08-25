package com.aioagent.business;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.timeout;
import static org.mockito.Mockito.verify;

import com.aioagent.business.config.AppProperties;
import com.aioagent.business.run.AgentCancellationPublisher;
import com.aioagent.business.run.AgentRunExecutor;
import com.aioagent.business.run.RedisAgentRunDispatcher;
import java.util.UUID;
import java.time.Duration;
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
    void streamConsumerRunsAndCanRestartWithExistingGroup() {
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
        RedisAgentRunDispatcher restartedDispatcher = new RedisAgentRunDispatcher(
                template,
                connectionFactory,
                runner,
                taskExecutor,
                properties,
                new SimpleMeterRegistry());
        try {
            dispatcher.start();
            UUID runId = UUID.randomUUID();
            String dispatchToken = UUID.randomUUID().toString();
            dispatcher.dispatch(runId, dispatchToken);
            verify(runner, timeout(5_000)).execute(runId, dispatchToken);
            UUID cancelledRunId = UUID.randomUUID();
            new AgentCancellationPublisher(template, properties).publish(cancelledRunId);
            assertEquals(
                    "1",
                    template.opsForValue().get(
                            properties.getRedis().getKeyPrefix() + ":run-cancelled:" + cancelledRunId));

            dispatcher.stop();
            restartedDispatcher.start();
            UUID restartedRunId = UUID.randomUUID();
            String restartedToken = UUID.randomUUID().toString();
            restartedDispatcher.dispatch(restartedRunId, restartedToken);
            verify(runner, timeout(5_000)).execute(restartedRunId, restartedToken);
        } finally {
            restartedDispatcher.stop();
            dispatcher.stop();
            taskExecutor.shutdown();
            connectionFactory.destroy();
        }
    }

    @Test
    void stalePendingDeliveryIsClaimedAfterAWorkerCrash() throws Exception {
        LettuceConnectionFactory connectionFactory = new LettuceConnectionFactory(
                REDIS.getHost(), REDIS.getMappedPort(6379));
        connectionFactory.afterPropertiesSet();
        connectionFactory.start();
        StringRedisTemplate template = new StringRedisTemplate(connectionFactory);
        template.afterPropertiesSet();
        ThreadPoolTaskExecutor taskExecutor = new ThreadPoolTaskExecutor();
        taskExecutor.setCorePoolSize(1);
        taskExecutor.setMaxPoolSize(1);
        taskExecutor.initialize();
        AgentRunExecutor runner = mock(AgentRunExecutor.class);
        AppProperties properties = new AppProperties();
        properties.getRedis().setEnabled(true);
        properties.getRedis().setRunStream("test:runs:reclaim:" + UUID.randomUUID());
        properties.getRedis().setRunGroup("test-reclaim-group");
        properties.getRedis().setPendingReclaimAfter(Duration.ZERO);
        RedisAgentRunDispatcher dispatcher = new RedisAgentRunDispatcher(
                template,
                connectionFactory,
                runner,
                taskExecutor,
                properties,
                new SimpleMeterRegistry());
        UUID runId = UUID.randomUUID();
        String dispatchToken = UUID.randomUUID().toString();
        doThrow(new IllegalStateException("simulated worker crash"))
                .doNothing()
                .when(runner)
                .execute(runId, dispatchToken);
        try {
            dispatcher.start();
            dispatcher.dispatch(runId, dispatchToken);
            verify(runner, timeout(5_000)).execute(runId, dispatchToken);

            dispatcher.reclaimPending();

            verify(runner, timeout(5_000).times(2)).execute(runId, dispatchToken);
            long deadline = System.nanoTime() + Duration.ofSeconds(5).toNanos();
            while (template.opsForStream().size(properties.getRedis().getRunStream()) != 0
                    && System.nanoTime() < deadline) {
                Thread.sleep(10);
            }
            assertEquals(0L, template.opsForStream().size(properties.getRedis().getRunStream()));
        } finally {
            dispatcher.stop();
            taskExecutor.shutdown();
            connectionFactory.destroy();
        }
    }
}
