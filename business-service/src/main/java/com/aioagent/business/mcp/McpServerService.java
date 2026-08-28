package com.aioagent.business.mcp;

import com.aioagent.business.agent.AgentServiceClient;
import com.aioagent.business.auth.UserAccount;
import com.aioagent.business.common.ApiException;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;
import tools.jackson.core.JacksonException;
import tools.jackson.databind.ObjectMapper;

@Service
public class McpServerService {

    private static final String QQ_MAIL_DISPLAY_NAME = "QQ 邮箱";
    private static final String QQ_MAIL_IMAP_HOST = "imap.qq.com";
    private static final int QQ_MAIL_IMAP_PORT = 993;
    private static final List<McpServerDtos.ToolView> QQ_MAIL_TOOLS = List.of(
            new McpServerDtos.ToolView("qq_mail_list_folders", "列出 QQ 邮箱目录", true),
            new McpServerDtos.ToolView("qq_mail_list_messages", "按服务器收件时间列出 QQ 邮件摘要", true),
            new McpServerDtos.ToolView("qq_mail_search_messages", "按日期、关键词、发件人或主题搜索 QQ 邮件", true),
            new McpServerDtos.ToolView("qq_mail_read_message", "读取指定目录中的 QQ 邮件正文和附件信息", true));

    private final McpServerConnectionRepository connections;
    private final ConnectorSecretCipher secrets;
    private final AgentServiceClient agentService;
    private final ObjectMapper mapper;
    private final TransactionTemplate transaction;

    public McpServerService(
            McpServerConnectionRepository connections,
            ConnectorSecretCipher secrets,
            AgentServiceClient agentService,
            ObjectMapper mapper,
            TransactionTemplate transaction) {
        this.connections = connections;
        this.secrets = secrets;
        this.agentService = agentService;
        this.mapper = mapper;
        this.transaction = transaction;
    }

    public McpServerDtos.ListResponse list(UserAccount user) {
        List<McpServerDtos.ServerView> servers = connections.findByOwnerIdOrderByUpdatedAtDesc(user.getId()).stream()
                .map(this::view)
                .toList();
        return new McpServerDtos.ListResponse(servers, List.of(new McpServerDtos.CatalogItem(
                "qq_mail",
                QQ_MAIL_DISPLAY_NAME,
                "通过内置 MCP Server 安全读取和搜索 QQ 邮件",
                "builtin",
                QQ_MAIL_TOOLS)));
    }

    public McpServerDtos.ServerView connectQqMail(
            UserAccount user,
            McpServerDtos.ConnectQqMailRequest request) {
        String email = request.email().strip().toLowerCase(Locale.ROOT);
        String imapHost = request.imapHost() == null || request.imapHost().isBlank()
                ? QQ_MAIL_IMAP_HOST
                : request.imapHost().strip().toLowerCase(Locale.ROOT);
        int imapPort = request.imapPort() == null ? QQ_MAIL_IMAP_PORT : request.imapPort();
        requireQqMailAddress(email);
        if (!QQ_MAIL_IMAP_HOST.equals(imapHost) || imapPort != QQ_MAIL_IMAP_PORT) {
            throw new ApiException(
                    HttpStatus.BAD_REQUEST,
                    "QQ_MAIL_HOST_NOT_ALLOWED",
                    "QQ 邮箱连接器只允许使用 imap.qq.com:993");
        }
        testConnection(email, request.authorizationCode(), imapHost, imapPort);

        Map<String, Object> config = new LinkedHashMap<>();
        config.put("email", email);
        config.put("imap_host", imapHost);
        config.put("imap_port", imapPort);
        String configJson = encode(config);
        String encrypted = secrets.encrypt(request.authorizationCode(), context(user.getId(), McpServerKind.QQ_MAIL));

        McpServerConnection saved = transaction.execute(status -> {
            McpServerConnection connection = connections
                    .findLockedByOwnerIdAndKind(user.getId(), McpServerKind.QQ_MAIL)
                    .orElseGet(() -> new McpServerConnection(
                            user,
                            McpServerKind.QQ_MAIL,
                            QQ_MAIL_DISPLAY_NAME,
                            configJson,
                            encrypted));
            if (connection.getId() != null) {
                connection.reconnect(QQ_MAIL_DISPLAY_NAME, configJson, encrypted);
            }
            return connections.save(connection);
        });
        if (saved == null) {
            throw new IllegalStateException("QQ Mail connection transaction returned no result");
        }
        return view(saved);
    }

    public McpServerDtos.ServerView test(UserAccount user, UUID id) {
        McpServerConnection connection = requireOwned(user, id);
        QqMailConfig config = decodeQqMailConfig(connection.getConfigJson());
        String authorizationCode = secrets.decrypt(
                connection.getEncryptedSecret(),
                context(user.getId(), connection.getKind()));
        try {
            testConnection(config.email(), authorizationCode, config.imapHost(), config.imapPort());
            return updateStatus(user, id, true, null);
        } catch (RuntimeException exception) {
            updateStatus(user, id, false, "QQ_MAIL_CONNECTION_FAILED");
            throw exception;
        }
    }

    public McpServerDtos.ServerView setEnabled(UserAccount user, UUID id, boolean enabled) {
        McpServerConnection saved = transaction.execute(status -> {
            McpServerConnection connection = connections.findByIdAndOwnerId(id, user.getId())
                    .orElseThrow(() -> notFound());
            connection.setEnabled(enabled);
            return connections.save(connection);
        });
        if (saved == null) {
            throw new IllegalStateException("MCP Server update transaction returned no result");
        }
        return view(saved);
    }

    public void delete(UserAccount user, UUID id) {
        McpServerConnection connection = requireOwned(user, id);
        connections.delete(connection);
    }

    public List<AgentServiceClient.McpServerConfig> executionConfigs(UUID userId) {
        return connections.findByOwnerIdAndEnabledTrueAndStatus(userId, McpServerStatus.CONNECTED).stream()
                .map(connection -> {
                    Map<String, Object> config = decodeMap(connection.getConfigJson());
                    String authorizationCode = secrets.decrypt(
                            connection.getEncryptedSecret(),
                            context(userId, connection.getKind()));
                    return new AgentServiceClient.McpServerConfig(
                            connection.getId(),
                            kindValue(connection.getKind()),
                            connection.getDisplayName(),
                            config,
                            Map.of("authorization_code", authorizationCode));
                })
                .toList();
    }

    private McpServerDtos.ServerView updateStatus(UserAccount user, UUID id, boolean connected, String errorCode) {
        McpServerConnection saved = transaction.execute(status -> {
            McpServerConnection connection = connections.findByIdAndOwnerId(id, user.getId())
                    .orElseThrow(() -> notFound());
            if (connected) {
                connection.markConnected();
            } else {
                connection.markError(errorCode);
            }
            return connections.save(connection);
        });
        if (saved == null) {
            throw new IllegalStateException("MCP Server status transaction returned no result");
        }
        return view(saved);
    }

    private void testConnection(String email, String authorizationCode, String imapHost, int imapPort) {
        try {
            AgentServiceClient.QqMailTestResponse response = agentService.testQqMail(
                    new AgentServiceClient.QqMailTestRequest(email, authorizationCode, imapHost, imapPort));
            if (response == null || !response.ok()) {
                throw new ApiException(
                        HttpStatus.BAD_GATEWAY,
                        "QQ_MAIL_CONNECTION_FAILED",
                        "QQ 邮箱连接失败，请检查是否开启 IMAP 服务以及授权码是否正确");
            }
        } catch (ApiException exception) {
            throw exception;
        } catch (RuntimeException exception) {
            throw new ApiException(
                    HttpStatus.BAD_GATEWAY,
                    "QQ_MAIL_CONNECTION_FAILED",
                    "QQ 邮箱连接失败，请检查是否开启 IMAP 服务以及授权码是否正确");
        }
    }

    private McpServerConnection requireOwned(UserAccount user, UUID id) {
        return connections.findByIdAndOwnerId(id, user.getId()).orElseThrow(this::notFound);
    }

    private ApiException notFound() {
        return new ApiException(HttpStatus.NOT_FOUND, "MCP_SERVER_NOT_FOUND", "MCP Server 不存在");
    }

    private void requireQqMailAddress(String email) {
        if (!(email.endsWith("@qq.com") || email.endsWith("@vip.qq.com") || email.endsWith("@foxmail.com"))) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "QQ_MAIL_ADDRESS_REQUIRED", "请输入 QQ 邮箱地址");
        }
    }

    private McpServerDtos.ServerView view(McpServerConnection connection) {
        QqMailConfig config = decodeQqMailConfig(connection.getConfigJson());
        return new McpServerDtos.ServerView(
                connection.getId(),
                kindValue(connection.getKind()),
                connection.getDisplayName(),
                "builtin",
                connection.isEnabled(),
                connection.getStatus().name().toLowerCase(Locale.ROOT),
                maskEmail(config.email()),
                true,
                QQ_MAIL_TOOLS,
                connection.getLastCheckedAt(),
                connection.getLastErrorCode(),
                connection.getCreatedAt(),
                connection.getUpdatedAt());
    }

    private String maskEmail(String email) {
        int separator = email.indexOf('@');
        if (separator <= 0) {
            return "****";
        }
        String local = email.substring(0, separator);
        String visible = local.substring(0, Math.min(2, local.length()));
        return visible + "****" + email.substring(separator);
    }

    private String kindValue(McpServerKind kind) {
        return switch (kind) {
            case QQ_MAIL -> "qq_mail";
        };
    }

    private String context(UUID ownerId, McpServerKind kind) {
        return ownerId + ":" + kind.name();
    }

    private String encode(Map<String, Object> value) {
        try {
            return mapper.writeValueAsString(value);
        } catch (JacksonException exception) {
            throw new IllegalStateException("Failed to encode MCP Server configuration", exception);
        }
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> decodeMap(String value) {
        try {
            Object decoded = mapper.readValue(value, Object.class);
            if (decoded instanceof Map<?, ?> map) {
                return (Map<String, Object>) map;
            }
            throw new IllegalStateException("MCP Server configuration is not an object");
        } catch (JacksonException exception) {
            throw new IllegalStateException("Failed to decode MCP Server configuration", exception);
        }
    }

    private QqMailConfig decodeQqMailConfig(String value) {
        Map<String, Object> config = decodeMap(value);
        String email = String.valueOf(config.getOrDefault("email", ""));
        String host = String.valueOf(config.getOrDefault("imap_host", QQ_MAIL_IMAP_HOST));
        Object rawPort = config.getOrDefault("imap_port", QQ_MAIL_IMAP_PORT);
        int port = rawPort instanceof Number number ? number.intValue() : Integer.parseInt(rawPort.toString());
        return new QqMailConfig(email, host, port);
    }

    private record QqMailConfig(String email, String imapHost, int imapPort) {
    }
}
