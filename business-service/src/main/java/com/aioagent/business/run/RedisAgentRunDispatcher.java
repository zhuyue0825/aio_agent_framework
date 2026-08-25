package com.aioagent.business.run;

import com.aioagent.business.config.AppProperties;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.Map;
import java.util.List;
import java.util.UUID;
import org.springframework.data.domain.Range;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.SmartLifecycle;
import org.springframework.dao.DataAccessException;
import org.springframework.data.redis.connection.RedisConnectionFactory;
import org.springframework.data.redis.connection.stream.Consumer;
import org.springframework.data.redis.connection.stream.MapRecord;
import org.springframework.data.redis.connection.stream.PendingMessages;
import org.springframework.data.redis.connection.stream.ReadOffset;
import org.springframework.data.redis.connection.stream.RecordId;
import org.springframework.data.redis.connection.stream.StreamOffset;
import org.springframework.data.redis.connection.stream.StreamRecords;
import org.springframework.data.redis.core.RedisCallback;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.stream.StreamMessageListenerContainer;
import org.springframework.scheduling.concurrent.ThreadPoolTaskExecutor;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import io.micrometer.core.instrument.Gauge;
import io.micrometer.core.instrument.MeterRegistry;

@Component
@ConditionalOnProperty(prefix = "app.redis", name = "enabled", havingValue = "true")
public class RedisAgentRunDispatcher implements AgentRunDispatcher, SmartLifecycle {

    private static final Logger log = LoggerFactory.getLogger(RedisAgentRunDispatcher.class);
    private final StringRedisTemplate redis;
    private final RedisConnectionFactory connectionFactory;
    private final AgentRunExecutor runner;
    private final ThreadPoolTaskExecutor taskExecutor;
    private final String stream;
    private final String group;
    private final Duration pendingReclaimAfter;
    private final String consumerName = UUID.randomUUID().toString();
    private volatile StreamMessageListenerContainer<String, MapRecord<String, String, String>> container;
    private volatile boolean running;

    public RedisAgentRunDispatcher(
            StringRedisTemplate redis,
            RedisConnectionFactory connectionFactory,
            AgentRunExecutor runner,
            ThreadPoolTaskExecutor taskExecutor,
            AppProperties properties,
            MeterRegistry meterRegistry) {
        this.redis = redis;
        this.connectionFactory = connectionFactory;
        this.runner = runner;
        this.taskExecutor = taskExecutor;
        this.stream = properties.getRedis().getRunStream();
        this.group = properties.getRedis().getRunGroup();
        this.pendingReclaimAfter = properties.getRedis().getPendingReclaimAfter();
        Gauge.builder("aio.agent.redis.queue.depth", this, RedisAgentRunDispatcher::queueDepth)
                .register(meterRegistry);
    }

    @Override
    public void dispatch(UUID runId, String dispatchToken) {
        redis.opsForStream().add(StreamRecords.mapBacked(Map.of(
                "run_id", runId.toString(),
                "dispatch_token", dispatchToken)).withStreamKey(stream));
    }

    @Override
    public synchronized void start() {
        if (running) {
            return;
        }
        createGroup();
        var options = StreamMessageListenerContainer.StreamMessageListenerContainerOptions
                .<String, MapRecord<String, String, String>>builder()
                .pollTimeout(Duration.ofSeconds(1))
                .errorHandler(error -> {
                    if (running) {
                        log.warn("redis_agent_run_listener_error", error);
                    } else {
                        log.debug("Redis Agent listener stopped", error);
                    }
                })
                .build();
        container = StreamMessageListenerContainer.create(connectionFactory, options);
        container.receive(
                Consumer.from(group, consumerName),
                StreamOffset.create(stream, ReadOffset.lastConsumed()),
                this::receive);
        container.start();
        running = true;
    }

    private void receive(MapRecord<String, ?, ?> record) {
        Object rawRunValue = record.getValue().get("run_id");
        Object dispatchTokenValue = record.getValue().get("dispatch_token");
        String rawRunId = rawRunValue == null ? null : rawRunValue.toString();
        String dispatchToken = dispatchTokenValue == null ? null : dispatchTokenValue.toString();
        UUID runId;
        try {
            runId = UUID.fromString(rawRunId);
        } catch (RuntimeException exception) {
            log.atWarn().addKeyValue("stream_record_id", record.getId()).log("redis_agent_run_record_invalid");
            acknowledge(record);
            return;
        }
        if (dispatchToken == null || dispatchToken.isBlank()) {
            acknowledge(record);
            return;
        }
        try {
            taskExecutor.execute(() -> {
                try {
                    runner.execute(runId, dispatchToken);
                    acknowledge(record);
                } catch (RuntimeException exception) {
                    log.atWarn()
                            .addKeyValue("run_id", runId)
                            .addKeyValue("stream_record_id", record.getId())
                            .log("redis_agent_run_execution_failed", exception);
                }
            });
        } catch (RuntimeException exception) {
            log.atWarn()
                    .addKeyValue("run_id", runId)
                    .addKeyValue("stream_record_id", record.getId())
                    .log("redis_agent_run_delivery_failed", exception);
        }
    }

    @Scheduled(fixedDelayString = "${app.redis.pending-reclaim-interval:30s}")
    public void reclaimPending() {
        if (!running) {
            return;
        }
        try {
            PendingMessages pending = redis.opsForStream().pending(
                    stream,
                    group,
                    Range.unbounded(),
                    100,
                    pendingReclaimAfter);
            List<RecordId> stale = pending.stream()
                    .map(message -> message.getId())
                    .toList();
            if (stale.isEmpty()) {
                return;
            }
            List<? extends MapRecord<String, ?, ?>> claimed = redis.opsForStream().claim(
                    stream,
                    group,
                    consumerName,
                    pendingReclaimAfter,
                    stale.toArray(RecordId[]::new));
            claimed.forEach(this::receive);
        } catch (DataAccessException exception) {
            log.debug("redis_agent_run_pending_reclaim_failed", exception);
        }
    }

    private void acknowledge(MapRecord<String, ?, ?> record) {
        redis.opsForStream().acknowledge(group, record);
        redis.opsForStream().delete(stream, record.getId());
    }

    private void createGroup() {
        byte[] key = stream.getBytes(StandardCharsets.UTF_8);
        byte[] groupName = group.getBytes(StandardCharsets.UTF_8);
        try {
            redis.execute((RedisCallback<Object>) connection -> connection.execute(
                    "XGROUP",
                    "CREATE".getBytes(StandardCharsets.UTF_8),
                    key,
                    groupName,
                    "0".getBytes(StandardCharsets.UTF_8),
                    "MKSTREAM".getBytes(StandardCharsets.UTF_8)));
        } catch (DataAccessException exception) {
            if (!isGroupAlreadyExists(exception)) {
                throw exception;
            }
        }
    }

    private boolean isGroupAlreadyExists(Throwable exception) {
        Throwable current = exception;
        while (current != null) {
            String message = current.getMessage();
            if (message != null && message.contains("BUSYGROUP")) {
                return true;
            }
            current = current.getCause();
        }
        return false;
    }

    private double queueDepth() {
        try {
            Long size = redis.opsForStream().size(stream);
            return size == null ? 0 : size.doubleValue();
        } catch (DataAccessException exception) {
            return Double.NaN;
        }
    }

    @Override
    public synchronized void stop() {
        running = false;
        if (container != null) {
            CountDownLatch stopped = new CountDownLatch(1);
            container.stop(stopped::countDown);
            try {
                stopped.await(5, TimeUnit.SECONDS);
            } catch (InterruptedException exception) {
                Thread.currentThread().interrupt();
            }
            container = null;
        }
    }

    @Override
    public boolean isRunning() {
        return running;
    }

    @Override
    public int getPhase() {
        return Integer.MIN_VALUE + 100;
    }
}
