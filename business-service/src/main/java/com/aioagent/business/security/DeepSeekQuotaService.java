package com.aioagent.business.security;

import com.aioagent.business.common.ApiException;
import com.aioagent.business.config.AppProperties;
import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneId;
import java.time.ZonedDateTime;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

@Service
public class DeepSeekQuotaService {

    private final JdbcTemplate database;
    private final AppProperties properties;

    public DeepSeekQuotaService(JdbcTemplate database, AppProperties properties) {
        this.database = database;
        this.properties = properties;
    }

    public Snapshot snapshot(UUID userId) {
        ZoneId zone = ZoneId.of(properties.getSecurity().getQuotaTimeZone());
        ZonedDateTime now = ZonedDateTime.now(zone);
        LocalDate quotaDate = now.toLocalDate();
        Instant resetsAt = quotaDate.plusDays(1).atStartOfDay(zone).toInstant();
        int limit = Math.max(0, properties.getSecurity().getDeepseekRunsPerDay());
        Long stored = database.query(
                """
                select used from model_daily_quotas
                where user_id = ? and provider = 'remote' and quota_date = ?
                """,
                result -> result.next() ? result.getLong("used") : 0L,
                userId,
                java.sql.Date.valueOf(quotaDate));
        long used = stored == null ? 0L : stored;
        Long remaining = limit <= 0 ? null : Math.max(0L, limit - used);
        return new Snapshot(limit, used, remaining, resetsAt, properties.getSecurity().getQuotaTimeZone());
    }

    public void requireAvailable(UUID userId) {
        Snapshot quota = snapshot(userId);
        if (quota.remaining() != null && quota.remaining() <= 0) {
            throw exhausted();
        }
    }

    public void consume(UUID userId) {
        Snapshot quota = snapshot(userId);
        if (quota.limit() <= 0) {
            return;
        }
        if (quota.remaining() == null || quota.remaining() <= 0) {
            throw exhausted();
        }
        ZoneId zone = ZoneId.of(properties.getSecurity().getQuotaTimeZone());
        LocalDate quotaDate = ZonedDateTime.now(zone).toLocalDate();
        database.update(
                """
                insert into model_daily_quotas(user_id, provider, quota_date, used, updated_at)
                values (?, 'remote', ?, 1, now())
                on conflict (user_id, provider, quota_date)
                do update set used = model_daily_quotas.used + 1, updated_at = now()
                """,
                userId,
                java.sql.Date.valueOf(quotaDate));
    }

    private ApiException exhausted() {
        return new ApiException(
                HttpStatus.TOO_MANY_REQUESTS,
                "DEEPSEEK_DAILY_QUOTA_EXCEEDED",
                "今日 DeepSeek 使用次数已用完，请改用 MiniMind 或明天再试");
    }

    public record Snapshot(int limit, long used, Long remaining, Instant resetsAt, String timeZone) {
    }
}
