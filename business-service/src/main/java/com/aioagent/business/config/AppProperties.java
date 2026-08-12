package com.aioagent.business.config;

import java.time.Duration;
import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "app")
public class AppProperties {

    private final Security security = new Security();
    private final Agent agent = new Agent();
    private final Bootstrap bootstrap = new Bootstrap();
    private final LegacyImport legacyImport = new LegacyImport();

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

    public static class Security {
        private String jwtSecret = "local-development-secret-change-before-production-0123456789";
        private Duration tokenTtl = Duration.ofHours(12);

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
    }

    public static class Agent {
        private String baseUrl = "http://127.0.0.1:8000";
        private String callbackBaseUrl = "http://127.0.0.1:8081";
        private String internalToken = "local-internal-token-change-before-production";
        private Duration connectTimeout = Duration.ofSeconds(3);
        private Duration readTimeout = Duration.ofMinutes(3);

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
    }

    public static class Bootstrap {
        private String adminUsername = "admin";
        private String adminPassword = "aio-local-admin";

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
}
