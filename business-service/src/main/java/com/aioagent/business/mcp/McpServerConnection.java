package com.aioagent.business.mcp;

import com.aioagent.business.auth.UserAccount;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.FetchType;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.Table;
import jakarta.persistence.Version;
import java.time.Instant;
import java.util.UUID;

@Entity
@Table(name = "mcp_server_connections")
public class McpServerConnection {

    @Id
    @GeneratedValue(strategy = GenerationType.UUID)
    private UUID id;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "owner_id", nullable = false)
    private UserAccount owner;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 40)
    private McpServerKind kind;

    @Column(name = "display_name", nullable = false, length = 120)
    private String displayName;

    @Column(nullable = false)
    private boolean enabled;

    @Column(name = "config_json", nullable = false, columnDefinition = "text")
    private String configJson;

    @Column(name = "encrypted_secret", nullable = false, columnDefinition = "text")
    private String encryptedSecret;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 20)
    private McpServerStatus status;

    @Column(name = "last_checked_at")
    private Instant lastCheckedAt;

    @Column(name = "last_error_code", length = 80)
    private String lastErrorCode;

    @Column(name = "created_at", nullable = false)
    private Instant createdAt;

    @Column(name = "updated_at", nullable = false)
    private Instant updatedAt;

    @Version
    @Column(nullable = false)
    private long version;

    protected McpServerConnection() {
    }

    public McpServerConnection(
            UserAccount owner,
            McpServerKind kind,
            String displayName,
            String configJson,
            String encryptedSecret) {
        this.owner = owner;
        this.kind = kind;
        this.displayName = displayName;
        this.enabled = true;
        this.configJson = configJson;
        this.encryptedSecret = encryptedSecret;
        this.status = McpServerStatus.CONNECTED;
        this.lastCheckedAt = Instant.now();
        this.createdAt = Instant.now();
        this.updatedAt = this.createdAt;
    }

    public void reconnect(String displayName, String configJson, String encryptedSecret) {
        this.displayName = displayName;
        this.configJson = configJson;
        this.encryptedSecret = encryptedSecret;
        this.enabled = true;
        markConnected();
    }

    public void setEnabled(boolean enabled) {
        this.enabled = enabled;
        this.updatedAt = Instant.now();
    }

    public void markConnected() {
        this.status = McpServerStatus.CONNECTED;
        this.lastCheckedAt = Instant.now();
        this.lastErrorCode = null;
        this.updatedAt = this.lastCheckedAt;
    }

    public void markError(String errorCode) {
        this.status = McpServerStatus.ERROR;
        this.lastCheckedAt = Instant.now();
        this.lastErrorCode = errorCode == null ? "QQ_MAIL_CONNECTION_FAILED" : errorCode;
        this.updatedAt = this.lastCheckedAt;
    }

    public UUID getId() {
        return id;
    }

    public UserAccount getOwner() {
        return owner;
    }

    public McpServerKind getKind() {
        return kind;
    }

    public String getDisplayName() {
        return displayName;
    }

    public boolean isEnabled() {
        return enabled;
    }

    public String getConfigJson() {
        return configJson;
    }

    public String getEncryptedSecret() {
        return encryptedSecret;
    }

    public McpServerStatus getStatus() {
        return status;
    }

    public Instant getLastCheckedAt() {
        return lastCheckedAt;
    }

    public String getLastErrorCode() {
        return lastErrorCode;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    public Instant getUpdatedAt() {
        return updatedAt;
    }
}
