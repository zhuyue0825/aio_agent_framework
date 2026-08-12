package com.aioagent.business;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.aioagent.business.agent.AgentServiceClient;
import com.aioagent.business.auth.AuthService;
import com.aioagent.business.auth.UserAccount;
import com.aioagent.business.auth.UserRepository;
import com.aioagent.business.common.ApiException;
import com.aioagent.business.config.AppProperties;
import com.aioagent.business.conversation.Conversation;
import com.aioagent.business.conversation.ConversationMode;
import com.aioagent.business.conversation.ConversationService;
import com.aioagent.business.project.ProjectService;
import com.aioagent.business.migration.LegacySqliteImporter;
import com.aioagent.business.run.AgentRunService;
import java.nio.file.Path;
import java.sql.DriverManager;
import java.sql.Statement;
import java.util.Map;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.DefaultApplicationArguments;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.testcontainers.service.connection.ServiceConnection;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.web.client.RestClient;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;
import org.testcontainers.postgresql.PostgreSQLContainer;

@Testcontainers
@SpringBootTest(properties = {
        "app.bootstrap.admin-username=integration-admin",
        "app.bootstrap.admin-password=integration-password",
        "app.security.jwt-secret=integration-test-secret-with-at-least-thirty-two-bytes",
        "app.agent.internal-token=integration-internal-token",
        "app.legacy-import.enabled=false"
})
@AutoConfigureMockMvc
class BusinessServiceIntegrationTest {

    @Container
    @ServiceConnection
    static final PostgreSQLContainer POSTGRES = new PostgreSQLContainer("postgres:17-alpine")
            .withDatabaseName("aio_agent_test")
            .withUsername("aio_agent")
            .withPassword("aio_agent_test");

    @Autowired
    MockMvc mockMvc;

    @Autowired
    JdbcTemplate jdbcTemplate;

    @Autowired
    UserRepository users;

    @Autowired
    AuthService authService;

    @Autowired
    ConversationService conversations;

    @Autowired
    AgentRunService runs;

    @Autowired
    ProjectService projects;

    @Autowired
    AppProperties properties;

    @Autowired
    LegacySqliteImporter legacyImporter;

    @Autowired
    RestClient.Builder restClientBuilder;

    @MockitoBean
    AgentServiceClient agentService;

    @Test
    void flywayCreatesSchemaAndSecurityIssuesJwt() throws Exception {
        Integer migrationCount = jdbcTemplate.queryForObject(
                "select count(*) from flyway_schema_history where success = true",
                Integer.class);
        assertThat(migrationCount).isEqualTo(1);
        assertThat(restClientBuilder).isNotNull();
        assertThat(users.findByUsernameIgnoreCase("integration-admin")).isPresent();

        mockMvc.perform(get("/api/v1/conversations"))
                .andExpect(status().isUnauthorized());

        mockMvc.perform(post("/api/v1/auth/login")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"username":"integration-admin","password":"integration-password"}
                                """))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.access_token").isNotEmpty())
                .andExpect(jsonPath("$.user.username").value("integration-admin"));
    }

    @Test
    void runCreationIsIdempotentAndEnforcesOneActiveRunPerConversation() {
        UserAccount user = authService.register("run-owner", "password-1234").user();
        Conversation conversation = conversations.create(user, "幂等测试", null, ConversationMode.CHAT);

        AgentRunService.CreateResult first = runs.create(
                user,
                conversation.getId(),
                "解释项目结构",
                ConversationMode.CHAT,
                null,
                "auto",
                8,
                "idempotency-key-001",
                "trace-integration-001");
        AgentRunService.CreateResult replay = runs.create(
                user,
                conversation.getId(),
                "解释项目结构",
                ConversationMode.CHAT,
                null,
                "auto",
                8,
                "idempotency-key-001",
                "trace-integration-001");

        assertThat(first.created()).isTrue();
        assertThat(replay.created()).isFalse();
        assertThat(replay.run().getId()).isEqualTo(first.run().getId());
        assertThatThrownBy(() -> runs.create(
                        user,
                        conversation.getId(),
                        "另一个并发任务",
                        ConversationMode.CHAT,
                        null,
                        "auto",
                        8,
                        "idempotency-key-002",
                        "trace-integration-002"))
                .isInstanceOf(ApiException.class)
                .hasMessageContaining("已有运行中的任务");
    }

    @Test
    void projectMembershipProtectsWorkspaceBusinessOperations() {
        UserAccount owner = authService.register("project-owner", "password-1234").user();
        UserAccount member = authService.register("project-member", "password-1234").user();
        when(agentService.openWorkspace(anyString())).thenReturn(Map.of(
                "workspace",
                Map.of("root", "/workspace/demo", "name", "demo", "tree", java.util.List.of())));

        ProjectService.OpenProjectResult opened = projects.open(owner, "/workspace/demo");
        assertThatThrownBy(() -> projects.requireMember(opened.project().getId(), member))
                .isInstanceOf(ApiException.class)
                .hasMessageContaining("无访问权限");

        projects.addMember(opened.project().getId(), owner, member.getUsername());
        assertThat(projects.requireMember(opened.project().getId(), member).getId())
                .isEqualTo(opened.project().getId());
    }

    @Test
    void legacySqliteImportIsReadOnlyAndIdempotent(@TempDir Path tempDir) throws Exception {
        Path sqlite = tempDir.resolve("legacy.sqlite3");
        UUID conversationId = UUID.randomUUID();
        UUID messageId = UUID.randomUUID();
        try (var connection = DriverManager.getConnection("jdbc:sqlite:" + sqlite);
                Statement statement = connection.createStatement()) {
            statement.executeUpdate("""
                    create table conversations (
                        id text primary key, title text not null, created_at real not null, updated_at real not null
                    )
                    """);
            statement.executeUpdate("""
                    create table messages (
                        id text primary key, conversation_id text not null, role text not null,
                        content text not null, metadata_json text not null, created_at real not null
                    )
                    """);
            statement.executeUpdate("insert into conversations values ('" + conversationId
                    + "', '旧对话', 1700000000, 1700000001)");
            statement.executeUpdate("insert into messages values ('" + messageId + "', '" + conversationId
                    + "', 'user', '旧消息', '{}', 1700000000)");
        }

        properties.getLegacyImport().setEnabled(true);
        properties.getLegacyImport().setSqlitePath(sqlite.toString());
        properties.getLegacyImport().setOwnerUsername("integration-admin");
        try {
            legacyImporter.run(new DefaultApplicationArguments(new String[0]));
            legacyImporter.run(new DefaultApplicationArguments(new String[0]));
        } finally {
            properties.getLegacyImport().setEnabled(false);
        }

        assertThat(jdbcTemplate.queryForObject(
                "select count(*) from conversations where id = ?",
                Integer.class,
                conversationId)).isEqualTo(1);
        assertThat(jdbcTemplate.queryForObject(
                "select count(*) from messages where id = ?",
                Integer.class,
                messageId)).isEqualTo(1);
        assertThat(jdbcTemplate.queryForObject(
                "select count(*) from legacy_imports where import_key = ?",
                Integer.class,
                "sqlite:" + sqlite.toAbsolutePath().normalize())).isEqualTo(1);
    }
}
