package com.aioagent.business.run;

import com.aioagent.business.config.AppProperties;
import java.time.Duration;
import java.util.UUID;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.dao.DataAccessException;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;

@Component
public class AgentCancellationPublisher {

    private static final Logger log = LoggerFactory.getLogger(AgentCancellationPublisher.class);
    private static final Duration TOMBSTONE_TTL = Duration.ofMinutes(10);
    private final StringRedisTemplate redis;
    private final AppProperties properties;

    public AgentCancellationPublisher(StringRedisTemplate redis, AppProperties properties) {
        this.redis = redis;
        this.properties = properties;
    }

    public void publish(UUID runId) {
        if (!properties.getRedis().isEnabled()) {
            return;
        }
        String prefix = properties.getRedis().getKeyPrefix();
        try {
            redis.opsForValue().set(prefix + ":run-cancelled:" + runId, "1", TOMBSTONE_TTL);
            redis.convertAndSend(prefix + ":run-cancel", runId.toString());
        } catch (DataAccessException exception) {
            log.atWarn()
                    .addKeyValue("run_id", runId)
                    .log("redis_agent_cancellation_publish_failed", exception);
        }
    }
}
