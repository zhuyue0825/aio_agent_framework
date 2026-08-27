package com.aioagent.business.config;

import java.time.Duration;
import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "app")
public class AppProperties {

    private final Security security = new Security();
    private final Agent agent = new Agent();
    private final Bootstrap bootstrap = new Bootstrap();
    private final LegacyImport legacyImport = new LegacyImport();
    private final Redis redis = new Redis();

    public Security getSecurity() {
        return security;
    }

    public Agent getAgent() {
        return agent;
    }

    public Bootstrap getBootstrap() {
        return bootstrap;
    }

    public LegacyImport getLegacyImport() {
        return legacyImport;
    }

    public Redis getRedis() {
        return redis;
    }

    public static class Security {
        private String jwtSecret;
        private Duration tokenTtl = Duration.ofMinutes(15);
        private Duration refreshTokenTtl = Duration.ofDays(30);
        private Duration passwordResetTtl = Duration.ofMinutes(30);
        private boolean refreshCookieSecure;
        private int loginAttemptsPerMinute = 10;
        private int runsPerMinute = 20;
        private long dailyTokenLimit = 200_000;
        private int deepseekRunsPerDay = 20;
        private String quotaTimeZone = "Asia/Shanghai";
        private boolean publicRegistrationEnabled;
        private String connectorEncryptionKey;

        public String getJwtSecret() {
            return jwtSecret;
        }

        public void setJwtSecret(String jwtSecret) {
            this.jwtSecret = jwtSecret;
        }

        public Duration getTokenTtl() {
            return tokenTtl;
        }

        public void setTokenTtl(Duration tokenTtl) {
            this.tokenTtl = tokenTtl;
        }

        public boolean isPublicRegistrationEnabled() {
            return publicRegistrationEnabled;
        }

        public void setPublicRegistrationEnabled(boolean publicRegistrationEnabled) {
            this.publicRegistrationEnabled = publicRegistrationEnabled;
        }

        public Duration getRefreshTokenTtl() {
            return refreshTokenTtl;
        }

        public void setRefreshTokenTtl(Duration refreshTokenTtl) {
            this.refreshTokenTtl = refreshTokenTtl;
        }

        public Duration getPasswordResetTtl() {
            return passwordResetTtl;
        }

        public void setPasswordResetTtl(Duration passwordResetTtl) {
            this.passwordResetTtl = passwordResetTtl;
        }

        public boolean isRefreshCookieSecure() {
            return refreshCookieSecure;
        }

        public void setRefreshCookieSecure(boolean refreshCookieSecure) {
            this.refreshCookieSecure = refreshCookieSecure;
        }

        public int getLoginAttemptsPerMinute() {
            return loginAttemptsPerMinute;
        }

        public void setLoginAttemptsPerMinute(int loginAttemptsPerMinute) {
            this.loginAttemptsPerMinute = loginAttemptsPerMinute;
        }

        public int getRunsPerMinute() {
            return runsPerMinute;
        }

        public void setRunsPerMinute(int runsPerMinute) {
            this.runsPerMinute = runsPerMinute;
        }

        public long getDailyTokenLimit() {
            return dailyTokenLimit;
        }

        public void setDailyTokenLimit(long dailyTokenLimit) {
            this.dailyTokenLimit = dailyTokenLimit;
        }

        public int getDeepseekRunsPerDay() {
            return deepseekRunsPerDay;
        }

        public void setDeepseekRunsPerDay(int deepseekRunsPerDay) {
            this.deepseekRunsPerDay = deepseekRunsPerDay;
        }

        public String getQuotaTimeZone() {
            return quotaTimeZone;
        }

        public void setQuotaTimeZone(String quotaTimeZone) {
            this.quotaTimeZone = quotaTimeZone;
        }

        public String getConnectorEncryptionKey() {
            return connectorEncryptionKey;
        }

        public void setConnectorEncryptionKey(String connectorEncryptionKey) {
            this.connectorEncryptionKey = connectorEncryptionKey;
        }
    }

    public static class Agent {
        private String baseUrl = "http://127.0.0.1:8000";
        private String callbackBaseUrl = "http://127.0.0.1:8081";
        private String internalToken;
        private Duration connectTimeout = Duration.ofSeconds(3);
        private Duration readTimeout = Duration.ofMinutes(3);
        private Duration recoveryStaleAfter = Duration.ofMinutes(4);
        private Duration heartbeatInterval = Duration.ofSeconds(30);
        private Duration dispatchLease = Duration.ofMinutes(5);
        private Duration changeApplyStaleAfter = Duration.ofMinutes(4);

        public String getBaseUrl() {
            return baseUrl;
        }

        public void setBaseUrl(String baseUrl) {
            this.baseUrl = baseUrl;
        }

        public String getCallbackBaseUrl() {
            return callbackBaseUrl;
        }

        public void setCallbackBaseUrl(String callbackBaseUrl) {
            this.callbackBaseUrl = callbackBaseUrl;
        }

        public String getInternalToken() {
            return internalToken;
        }

        public void setInternalToken(String internalToken) {
            this.internalToken = internalToken;
        }

        public Duration getConnectTimeout() {
            return connectTimeout;
        }

        public void setConnectTimeout(Duration connectTimeout) {
            this.connectTimeout = connectTimeout;
        }

        public Duration getReadTimeout() {
            return readTimeout;
        }

        public void setReadTimeout(Duration readTimeout) {
            this.readTimeout = readTimeout;
        }

        public Duration getRecoveryStaleAfter() {
            return recoveryStaleAfter;
        }

        public void setRecoveryStaleAfter(Duration recoveryStaleAfter) {
            this.recoveryStaleAfter = recoveryStaleAfter;
        }

        public Duration getHeartbeatInterval() {
            return heartbeatInterval;
        }

        public void setHeartbeatInterval(Duration heartbeatInterval) {
            this.heartbeatInterval = heartbeatInterval;
        }

        public Duration getDispatchLease() {
            return dispatchLease;
        }

        public void setDispatchLease(Duration dispatchLease) {
            this.dispatchLease = dispatchLease;
        }

        public Duration getChangeApplyStaleAfter() {
            return changeApplyStaleAfter;
        }

        public void setChangeApplyStaleAfter(Duration changeApplyStaleAfter) {
            this.changeApplyStaleAfter = changeApplyStaleAfter;
        }
    }

    public static class Bootstrap {
        private String adminUsername = "admin";
        private String adminPassword;

        public String getAdminUsername() {
            return adminUsername;
        }

        public void setAdminUsername(String adminUsername) {
            this.adminUsername = adminUsername;
        }

        public String getAdminPassword() {
            return adminPassword;
        }

        public void setAdminPassword(String adminPassword) {
            this.adminPassword = adminPassword;
        }
    }

    public static class LegacyImport {
        private boolean enabled;
        private String sqlitePath = "../data/app.sqlite3";
        private String ownerUsername = "admin";

        public boolean isEnabled() {
            return enabled;
        }

        public void setEnabled(boolean enabled) {
            this.enabled = enabled;
        }

        public String getSqlitePath() {
            return sqlitePath;
        }

        public void setSqlitePath(String sqlitePath) {
            this.sqlitePath = sqlitePath;
        }

        public String getOwnerUsername() {
            return ownerUsername;
        }

        public void setOwnerUsername(String ownerUsername) {
            this.ownerUsername = ownerUsername;
        }
    }

    public static class Redis {
        private boolean enabled;
        private String keyPrefix = "aio";
        private String runStream = "aio:agent-runs";
        private String runGroup = "aio-business";
        private String eventChannel = "aio:run-events";
        private Duration pendingReclaimAfter = Duration.ofMinutes(2);

        public boolean isEnabled() {
            return enabled;
        }

        public void setEnabled(boolean enabled) {
            this.enabled = enabled;
        }

        public String getKeyPrefix() {
            return keyPrefix;
        }

        public void setKeyPrefix(String keyPrefix) {
            this.keyPrefix = keyPrefix;
        }

        public String getRunStream() {
            return runStream;
        }

        public void setRunStream(String runStream) {
            this.runStream = runStream;
        }

        public String getRunGroup() {
            return runGroup;
        }

        public void setRunGroup(String runGroup) {
            this.runGroup = runGroup;
        }

        public String getEventChannel() {
            return eventChannel;
        }

        public void setEventChannel(String eventChannel) {
            this.eventChannel = eventChannel;
        }

        public Duration getPendingReclaimAfter() {
            return pendingReclaimAfter;
        }

        public void setPendingReclaimAfter(Duration pendingReclaimAfter) {
            this.pendingReclaimAfter = pendingReclaimAfter;
        }
    }
}
