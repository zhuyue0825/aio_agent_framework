package com.aioagent.business.mcp;

import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;
import java.time.Instant;
import java.util.List;
import java.util.UUID;

public final class McpServerDtos {

    private McpServerDtos() {
    }

    public record ToolView(String name, String description, boolean readOnly) {
    }

    public record CatalogItem(
            String kind,
            String displayName,
            String description,
            String transport,
            List<ToolView> tools) {
    }

    public record ServerView(
            UUID id,
            String kind,
            String displayName,
            String transport,
            boolean enabled,
            String status,
            String account,
            boolean credentialConfigured,
            List<ToolView> tools,
            Instant lastCheckedAt,
            String lastErrorCode,
            Instant createdAt,
            Instant updatedAt) {
    }

    public record ListResponse(List<ServerView> servers, List<CatalogItem> catalog) {
    }

    public record ServerResponse(ServerView server) {
    }

    public record ConnectQqMailRequest(
            @NotBlank @Email @Size(max = 254) String email,
            @NotBlank @Size(min = 8, max = 128) @Pattern(regexp = "\\S+") String authorizationCode,
            @Size(max = 253) @Pattern(regexp = "[A-Za-z0-9.-]+") String imapHost,
            @Min(1) @Max(65535) Integer imapPort) {
    }

    public record EnabledRequest(boolean enabled) {
    }
}
