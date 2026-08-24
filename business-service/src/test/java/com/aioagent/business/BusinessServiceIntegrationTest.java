package com.aioagent.business;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.asyncDispatch;
import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.jwt;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.request;
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
import com.aioagent.business.conversation.ConversationModelProvider;
import com.aioagent.business.conversation.ConversationService;
import com.aioagent.business.project.ProjectService;
import com.aioagent.business.migration.LegacySqliteImporter;
import com.aioagent.business.run.AgentRunService;
import com.aioagent.business.run.RunEvent;
import com.aioagent.business.run.RunEventRepository;
import java.nio.file.Path;
import java.sql.DriverManager;
import java.sql.Statement;
import java.util.Map;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import jakarta.servlet.http.Cookie;
import org.springframework.test.web.servlet.MvcResult;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.DefaultApplicationArguments;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.testcontainers.service.connection.ServiceConnection;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.http.MediaType;
import org.springframework.http.HttpHeaders;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
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
        "app.security.public-registration-enabled=true",
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
    RunEventRepository runEvents;

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
        assertThat(migrationCount).isEqualTo(6);
        assertThat(restClientBuilder).isNotNull();
        assertThat(users.findByUsernameIgnoreCase("integration-admin")).isPresent();

        mockMvc.perform(get("/api/v1/conversations"))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.error.code").value("UNAUTHORIZED"))
                .andExpect(jsonPath("$.error.trace_id").isNotEmpty());

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
    void publicRegistrationCanBeDisabled() throws Exception {
        properties.getSecurity().setPublicRegistrationEnabled(false);
        try {
            mockMvc.perform(post("/api/v1/auth/register")
                            .header("X-Trace-Id", "trace-registration-disabled")
                            .contentType(MediaType.APPLICATION_JSON)
                            .content("""
                                    {"username":"blocked-user","password":"password-1234"}
                                    """))
                    .andExpect(status().isForbidden())
                    .andExpect(jsonPath("$.error.code").value("REGISTRATION_DISABLED"))
                    .andExpect(jsonPath("$.error.trace_id").value("trace-registration-disabled"));
        } finally {
            properties.getSecurity().setPublicRegistrationEnabled(true);
        }
    }

    @Test
    void refreshTokenRotatesAndCannotBeReplayed() throws Exception {
        MvcResult login = mockMvc.perform(post("/api/v1/auth/login")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"username":"integration-admin","password":"integration-password"}
                                """))
                .andExpect(status().isOk())
                .andReturn();
        Cookie first = login.getResponse().getCookie("aio_refresh_token");
        assertThat(first).isNotNull();
        assertThat(first.isHttpOnly()).isTrue();

        mockMvc.perform(post("/api/v1/auth/refresh").cookie(first).contentType(MediaType.APPLICATION_JSON).content("{}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.access_token").isNotEmpty());

        mockMvc.perform(post("/api/v1/auth/refresh").cookie(first).contentType(MediaType.APPLICATION_JSON).content("{}"))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.error.code").value("INVALID_REFRESH_TOKEN"));
    }

    @Test
    void logoutRevokesCurrentAccessAndRefreshTokens() throws Exception {
        MvcResult login = mockMvc.perform(post("/api/v1/auth/login")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"username":"integration-admin","password":"integration-password"}
                                """))
                .andExpect(status().isOk())
                .andReturn();
        Cookie refresh = login.getResponse().getCookie("aio_refresh_token");
        String access = com.jayway.jsonpath.JsonPath.read(login.getResponse().getContentAsString(), "$.access_token");

        mockMvc.perform(post("/api/v1/auth/logout")
                        .cookie(refresh)
                        .header(HttpHeaders.AUTHORIZATION, "Bearer " + access)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{}"))
                .andExpect(status().isOk());

        mockMvc.perform(get("/api/v1/conversations")
                        .header(HttpHeaders.AUTHORIZATION, "Bearer " + access))
                .andExpect(status().isUnauthorized());
        mockMvc.perform(post("/api/v1/auth/refresh")
                        .cookie(refresh)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{}"))
                .andExpect(status().isUnauthorized());
    }

    @Test
    void passwordResetChangesCredentialsAndRevokesExistingRefreshTokens() {
        String suffix = UUID.randomUUID().toString().substring(0, 8);
        String username = "reset-user-" + suffix;
        AuthService.AuthResult original = authService.register(username, "password-1234");
        AuthService.ResetToken reset = authService.issuePasswordReset(username);

        authService.resetPassword(reset.value(), "password-5678");

        assertThatThrownBy(() -> authService.refresh(original.refreshToken()))
                .isInstanceOf(ApiException.class)
                .hasMessageContaining("登录会话无效");
        assertThatThrownBy(() -> authService.login(username, "password-1234"))
                .isInstanceOf(ApiException.class)
                .hasMessageContaining("用户名或密码错误");
        assertThat(authService.login(username, "password-5678").user().getUsername()).isEqualTo(username);
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

        UserAccount other = authService.register("other-run-user", "password-1234").user();
        assertThatThrownBy(() -> runs.require(other, first.run().getId()))
                .isInstanceOf(ApiException.class)
                .hasMessageContaining("不存在");
    }

    @Test
    void concurrentRunCreationAllowsOnlyOneActiveRunPerConversation() throws Exception {
        String suffix = UUID.randomUUID().toString().substring(0, 8);
        UserAccount user = authService.register("parallel-" + suffix, "password-1234").user();
        Conversation conversation = conversations.create(user, "并发测试", null, ConversationMode.CHAT);
        CountDownLatch ready = new CountDownLatch(2);
        CountDownLatch start = new CountDownLatch(1);
        ExecutorService executor = Executors.newFixedThreadPool(2);
        try {
            List<Future<Object>> futures = java.util.stream.IntStream.range(0, 2)
                    .mapToObj(index -> executor.submit(() -> {
                        ready.countDown();
                        start.await();
                        try {
                            return runs.create(
                                    user,
                                    conversation.getId(),
                                    "并发任务 " + index,
                                    ConversationMode.CHAT,
                                    null,
                                    "auto",
                                    8,
                                    "parallel-key-" + suffix + "-" + index,
                                    "parallel-trace-" + index);
                        } catch (ApiException exception) {
                            return exception;
                        }
                    }))
                    .toList();
            ready.await();
            start.countDown();
            List<Object> results = futures.stream().map(future -> {
                try {
                    return future.get();
                } catch (Exception exception) {
                    throw new AssertionError(exception);
                }
            }).toList();

            assertThat(results.stream().filter(AgentRunService.CreateResult.class::isInstance).count()).isEqualTo(1);
            assertThat(results.stream().filter(ApiException.class::isInstance).count()).isEqualTo(1);
        } finally {
            executor.shutdownNow();
        }
    }

    @Test
    void sseReconnectReplaysOnlyEventsAfterLastEventId() throws Exception {
        String suffix = UUID.randomUUID().toString().substring(0, 8);
        UserAccount user = authService.register("sse-" + suffix, "password-1234").user();
        Conversation conversation = conversations.create(user, "SSE 重连", null, ConversationMode.CHAT);
        var run = runs.create(
                user,
                conversation.getId(),
                "测试重连",
                ConversationMode.CHAT,
                null,
                "auto",
                8,
                "sse-key-" + suffix,
                "sse-trace-" + suffix).run();
        runs.cancel(user, run.getId());
        List<RunEvent> history = runEvents.findAllByRunIdOrderByIdAsc(run.getId());
        assertThat(history).hasSize(2);

        MvcResult stream = mockMvc.perform(get("/api/v1/runs/{runId}/events", run.getId())
                        .header("Last-Event-ID", history.get(0).getId())
                        .accept(MediaType.TEXT_EVENT_STREAM)
                        .with(jwt().jwt(token -> token
                                .subject(user.getId().toString())
                                .claim("role", "USER"))))
                .andExpect(request().asyncStarted())
                .andReturn();
        String body = mockMvc.perform(asyncDispatch(stream))
                .andExpect(status().isOk())
                .andReturn()
                .getResponse()
                .getContentAsString();

        assertThat(body).contains("id:" + history.get(1).getId(), "event:run.cancelled");
        assertThat(body).doesNotContain("id:" + history.get(0).getId() + "\n");
    }

    @Test
    void projectMembershipProtectsWorkspaceBusinessOperations() {
        UserAccount owner = authService.register("project-owner", "password-1234").user();
        UserAccount member = authService.register("project-member", "password-1234").user();
        when(agentService.openWorkspace(anyString(), any(UUID.class))).thenReturn(Map.of(
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
    void modelSettingsRequireAdminRoleAndNeverExposeApiKey() throws Exception {
        when(agentService.modelSettings()).thenReturn(Map.of(
                "active_provider", "remote",
                "active_model_name", "deepseek-v4-flash",
                "remote", Map.of(
                        "api_base", "https://api.deepseek.com",
                        "model_name", "deepseek-v4-flash",
                        "api_key_configured", true),
                "local", Map.of(
                        "api_base", "http://minimind:8998/v1",
                        "model_name", "minimind")));

        mockMvc.perform(get("/api/v1/model-settings")
                        .with(jwt().authorities(new SimpleGrantedAuthority("ROLE_USER"))))
                .andExpect(status().isForbidden());

        mockMvc.perform(get("/api/v1/model-settings")
                        .with(jwt().authorities(new SimpleGrantedAuthority("ROLE_ADMIN"))))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.active_provider").value("remote"))
                .andExpect(jsonPath("$.remote.api_key_configured").value(true))
                .andExpect(jsonPath("$.remote.api_key").doesNotExist());
    }

    @Test
    void regularUserCanSelectAConfiguredModelWithoutSeeingTheApiKey() throws Exception {
        String suffix = UUID.randomUUID().toString().substring(0, 8);
        UserAccount user = authService.register("model-user-" + suffix, "password-1234").user();
        Conversation conversation = conversations.create(user, "模型选择", null, ConversationMode.CHAT);
        stubConfiguredModels();

        mockMvc.perform(get("/api/v1/model-options")
                        .with(jwt().jwt(token -> token
                                .subject(user.getId().toString())
                                .claim("role", "USER"))))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.models[0].provider").value("local"))
                .andExpect(jsonPath("$.models[1].provider").value("remote"))
                .andExpect(jsonPath("$.models[1].available").value(true))
                .andExpect(jsonPath("$.models[1].api_key").doesNotExist())
                .andExpect(jsonPath("$.deepseek_quota.remaining").isNumber());

        mockMvc.perform(put("/api/v1/conversations/{conversationId}/model", conversation.getId())
                        .with(jwt().jwt(token -> token
                                .subject(user.getId().toString())
                                .claim("role", "USER")))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"model_provider":"remote"}
                                """))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.conversation.model_provider").value("remote"));
    }

    @Test
    void deepSeekDailyQuotaIsPerUserAndIdempotentReplaysDoNotConsumeIt() {
        int previousLimit = properties.getSecurity().getDeepseekRunsPerDay();
        properties.getSecurity().setDeepseekRunsPerDay(2);
        try {
            stubConfiguredModels();
            String suffix = UUID.randomUUID().toString().substring(0, 8);
            UserAccount user = authService.register("quota-user-" + suffix, "password-1234").user();
            Conversation conversation = conversations.create(
                    user,
                    "额度测试",
                    null,
                    ConversationMode.CHAT,
                    ConversationModelProvider.REMOTE);

            AgentRunService.CreateResult first = runs.create(
                    user,
                    conversation.getId(),
                    "第一次",
                    ConversationMode.CHAT,
                    null,
                    "auto",
                    8,
                    "quota-key-1-" + suffix,
                    "quota-trace-1");
            AgentRunService.CreateResult replay = runs.create(
                    user,
                    conversation.getId(),
                    "第一次",
                    ConversationMode.CHAT,
                    null,
                    "auto",
                    8,
                    "quota-key-1-" + suffix,
                    "quota-trace-1");
            assertThat(replay.created()).isFalse();
            assertThat(replay.run().getId()).isEqualTo(first.run().getId());
            runs.cancel(user, first.run().getId());

            AgentRunService.CreateResult second = runs.create(
                    user,
                    conversation.getId(),
                    "第二次",
                    ConversationMode.CHAT,
                    null,
                    "auto",
                    8,
                    "quota-key-2-" + suffix,
                    "quota-trace-2");
            runs.cancel(user, second.run().getId());

            conversations.delete(user, conversation.getId());
            Conversation afterDeletion = conversations.create(
                    user,
                    "删除会话后额度仍保留",
                    null,
                    ConversationMode.CHAT,
                    ConversationModelProvider.REMOTE);

            assertThatThrownBy(() -> runs.create(
                            user,
                            afterDeletion.getId(),
                            "第三次",
                            ConversationMode.CHAT,
                            null,
                            "auto",
                            8,
                            "quota-key-3-" + suffix,
                            "quota-trace-3"))
                    .isInstanceOfSatisfying(ApiException.class, exception ->
                            assertThat(exception.getCode()).isEqualTo("DEEPSEEK_DAILY_QUOTA_EXCEEDED"));

            UserAccount other = authService.register("quota-other-" + suffix, "password-1234").user();
            Conversation otherConversation = conversations.create(
                    other,
                    "独立额度",
                    null,
                    ConversationMode.CHAT,
                    ConversationModelProvider.REMOTE);
            assertThat(runs.create(
                            other,
                            otherConversation.getId(),
                            "其他用户第一次",
                            ConversationMode.CHAT,
                            null,
                            "auto",
                            8,
                            "quota-other-key-" + suffix,
                            "quota-other-trace")
                    .created()).isTrue();
        } finally {
            properties.getSecurity().setDeepseekRunsPerDay(previousLimit);
        }
    }

    private void stubConfiguredModels() {
        when(agentService.modelSettings()).thenReturn(Map.of(
                "active_provider", "local",
                "active_model_name", "minimind",
                "remote", Map.of(
                        "api_base", "https://api.deepseek.com",
                        "model_name", "deepseek-chat",
                        "api_key_configured", true),
                "local", Map.of(
                        "api_base", "http://minimind:8998/v1",
                        "model_name", "minimind")));
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
