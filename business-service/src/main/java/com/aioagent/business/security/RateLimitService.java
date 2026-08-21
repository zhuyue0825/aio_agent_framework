package com.aioagent.business.security;

import com.aioagent.business.common.ApiException;
import com.aioagent.business.config.AppProperties;
import java.time.Duration;
import java.time.Instant;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicInteger;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.dao.DataAccessException;
import java.util.List;

@Service
public class RateLimitService {

    private final ConcurrentHashMap<String, Window> windows = new ConcurrentHashMap<>();
    private final StringRedisTemplate redis;
    private final AppProperties properties;
    private static final DefaultRedisScript<Long> WINDOW_SCRIPT = new DefaultRedisScript<>("""
            local value = redis.call('INCR', KEYS[1])
            if value == 1 then redis.call('PEXPIRE', KEYS[1], ARGV[1]) end
            return value
            """, Long.class);

    public RateLimitService(StringRedisTemplate redis, AppProperties properties) {
        this.redis = redis;
        this.properties = properties;
    }

    public void require(String key, int limit, Duration duration) {
        if (limit <= 0) {
            return;
        }
        if (properties.getRedis().isEnabled()) {
            requireRedis(key, limit, duration);
            return;
        }
        Instant now = Instant.now();
        Window window = windows.compute(key, (ignored, current) -> {
            if (current == null || !current.expiresAt().isAfter(now)) {
                return new Window(new AtomicInteger(1), now.plus(duration));
            }
            current.count().incrementAndGet();
            return current;
        });
        if (window.count().get() > limit) {
            throw new ApiException(HttpStatus.TOO_MANY_REQUESTS, "RATE_LIMITED", "请求过于频繁，请稍后再试");
        }
        if (windows.size() > 10_000) {
            windows.entrySet().removeIf(entry -> !entry.getValue().expiresAt().isAfter(now));
        }
    }

    private void requireRedis(String key, int limit, Duration duration) {
        try {
            Long count = redis.execute(
                    WINDOW_SCRIPT,
                    List.of(properties.getRedis().getKeyPrefix() + ":rate:" + key),
                    String.valueOf(duration.toMillis()));
            if (count != null && count > limit) {
                throw new ApiException(HttpStatus.TOO_MANY_REQUESTS, "RATE_LIMITED", "请求过于频繁，请稍后再试");
            }
        } catch (DataAccessException exception) {
            throw new ApiException(HttpStatus.SERVICE_UNAVAILABLE, "RATE_LIMIT_UNAVAILABLE", "限流服务暂时不可用");
        }
    }

    private record Window(AtomicInteger count, Instant expiresAt) {
    }
}
