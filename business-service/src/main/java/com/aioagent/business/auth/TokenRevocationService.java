package com.aioagent.business.auth;

import java.time.Instant;
import java.util.concurrent.ConcurrentHashMap;
import org.springframework.stereotype.Service;
import com.aioagent.business.config.AppProperties;
import java.time.Duration;
import org.springframework.data.redis.core.StringRedisTemplate;

@Service
public class TokenRevocationService {

    private final ConcurrentHashMap<String, Instant> revoked = new ConcurrentHashMap<>();
    private final StringRedisTemplate redis;
    private final AppProperties properties;

    public TokenRevocationService(StringRedisTemplate redis, AppProperties properties) {
        this.redis = redis;
        this.properties = properties;
    }

    public void revoke(String jwtId, Instant expiresAt) {
        if (jwtId != null && !jwtId.isBlank() && expiresAt != null && expiresAt.isAfter(Instant.now())) {
            if (properties.getRedis().isEnabled()) {
                redis.opsForValue().set(key(jwtId), "1", Duration.between(Instant.now(), expiresAt));
            } else {
                revoked.put(jwtId, expiresAt);
            }
        }
    }

    public boolean isRevoked(String jwtId) {
        if (jwtId == null) {
            return false;
        }
        if (properties.getRedis().isEnabled()) {
            return Boolean.TRUE.equals(redis.hasKey(key(jwtId)));
        }
        Instant expiry = revoked.get(jwtId);
        if (expiry == null) {
            return false;
        }
        if (!expiry.isAfter(Instant.now())) {
            revoked.remove(jwtId, expiry);
            return false;
        }
        return true;
    }

    private String key(String jwtId) {
        return properties.getRedis().getKeyPrefix() + ":jwt:revoked:" + jwtId;
    }
}
