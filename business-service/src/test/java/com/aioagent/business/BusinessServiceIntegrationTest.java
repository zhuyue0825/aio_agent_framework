package com.aioagent.business;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
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
import com.aioagent.business.mcp.McpServerService;
import com.aioagent.business.migration.LegacySqliteImporter;
import com.aioagent.business.run.AgentRunService;
import com.aioagent.business.run.AgentRun;
import com.aioagent.business.run.RunEvent;
import com.aioagent.business.run.RunEventRepository;
import com.aioagent.business.run.RunStatus;
import com.aioagent.business.run.WorkspaceChangeService;
import com.aioagent.business.security.DeepSeekQuotaService;
import java.nio.file.Path;
import java.sql.DriverManager;
import java.sql.Statement;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.Map;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
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
    WorkspaceChangeService workspaceChanges;

    @Autowired
    DeepSeekQuotaService deepSeekQuotas;

    @Autowired
    RunEventRepository runEvents;

    @Autowired
    ProjectService projects;

    @Autowired
    McpServerService mcpServers;

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
        assertThat(migrationCount).isEqualTo(9);
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
    void passwordChangePersistsAndRevokesExistingRefreshTokens() {
        String suffix = UUID.randomUUID().toString().substring(0, 8);
        String username = "change-user-" + suffix;
        AuthService.AuthResult original = authService.register(username, "password-1234");

        authService.changePassword(original.user().getId(), "password-1234", "password-5678");

        assertThatThrownBy(() -> authService.login(username, "password-1234"))
                .isInstanceOf(ApiException.class)
                .hasMessageContaining("用户名或密码错误");
        assertThat(authService.login(username, "password-5678").user().getUsername()).isEqualTo(username);
        assertThatThrownBy(() -> authService.refresh(original.refreshToken()))
                .isInstanceOf(ApiException.class)
                .hasMessageContaining("登录会话无效");
    }

    @Test
    void concurrentRefreshAndPasswordChangeCannotLeaveAnOldSessionActive() throws Exception {
        String suffix = UUID.randomUUID().toString().substring(0, 8);
        String username = "credential-race-" + suffix;
        AuthService.AuthResult original = authService.register(username, "password-1234");
        CountDownLatch ready = new CountDownLatch(2);
        CountDownLatch start = new CountDownLatch(1);
        ExecutorService executor = Executors.newFixedThreadPool(2);
        try {
            Future<Object> refreshed = executor.submit(() -> {
                ready.countDown();
                start.await();
                try {
                    return authService.refresh(original.refreshToken());
                } catch (ApiException exception) {
                    return exception;
                }
            });
            Future<?> changed = executor.submit(() -> {
                ready.countDown();
                start.await();
                authService.changePassword(original.user().getId(), "password-1234", "password-5678");
                return null;
            });
            ready.await();
            start.countDown();
            Object refreshResult = refreshed.get();
            changed.get();

            if (refreshResult instanceof AuthService.AuthResult rotated) {
                assertThatThrownBy(() -> authService.refresh(rotated.refreshToken()))
                        .isInstanceOf(ApiException.class)
                        .hasMessageContaining("登录会话无效");
            }
            assertThatThrownBy(() -> authService.refresh(original.refreshToken()))
                    .isInstanceOf(ApiException.class)
                    .hasMessageContaining("登录会话无效");
            assertThat(authService.login(username, "password-5678").user().getUsername()).isEqualTo(username);
        } finally {
            executor.shutdownNow();
        }
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
    void dispatchLeaseUsesTokensToRejectStaleQueueDeliveries() {
        String suffix = UUID.randomUUID().toString().substring(0, 8);
        UserAccount user = authService.register("dispatch-" + suffix, "password-1234").user();
        Conversation conversation = conversations.create(user, "派发租约", null, ConversationMode.CHAT);
        AgentRun run = runs.create(
                user,
                conversation.getId(),
                "测试派发",
                ConversationMode.CHAT,
                null,
                "auto",
                8,
                "dispatch-key-" + suffix,
                "dispatch-trace-" + suffix).run();
        String firstToken = UUID.randomUUID().toString();
        String secondToken = UUID.randomUUID().toString();

        assertThat(runs.claimDispatch(run.getId(), firstToken)).isTrue();
        assertThat(runs.claimDispatch(run.getId(), secondToken)).isFalse();
        runs.releaseDispatch(run.getId(), firstToken);
        assertThat(runs.claimDispatch(run.getId(), secondToken)).isTrue();
        assertThat(runs.prepare(run.getId(), firstToken, "worker-old")).isEmpty();
        assertThat(runs.prepare(run.getId(), secondToken, "worker-current")).isPresent();

        runs.cancel(user, run.getId());
    }

    @Test
    void anActiveWorkerHeartbeatRenewsTheLeaseAndOnlyAnExpiredLeaseIsRecovered() {
        String suffix = UUID.randomUUID().toString().substring(0, 8);
        UserAccount user = authService.register("heartbeat-" + suffix, "password-1234").user();
        Conversation conversation = conversations.create(user, "心跳续租", null, ConversationMode.CHAT);
        AgentRun run = runs.create(
                user,
                conversation.getId(),
                "长任务",
                ConversationMode.CHAT,
                null,
                "auto",
                8,
                "heartbeat-key-" + suffix,
                "heartbeat-trace-" + suffix).run();
        String dispatchToken = UUID.randomUUID().toString();
        assertThat(runs.claimDispatch(run.getId(), dispatchToken)).isTrue();
        assertThat(runs.prepare(run.getId(), dispatchToken, "worker-live")).isPresent();
        AgentRun prepared = runs.require(user, run.getId());
        Instant firstLease = prepared.getLeaseExpiresAt();

        assertThat(runs.heartbeat(run.getId(), "worker-stale")).isFalse();
        assertThat(runs.heartbeat(run.getId(), "worker-live")).isTrue();
        AgentRun renewed = runs.require(user, run.getId());
        assertThat(renewed.getHeartbeatAt()).isNotNull();
        assertThat(renewed.getLeaseExpiresAt()).isAfterOrEqualTo(firstLease);
        assertThat(runs.expireStaleRun(run.getId(), Instant.now())).isFalse();

        jdbcTemplate.update(
                "update agent_runs set lease_expires_at = ? where id = ?",
                Timestamp.from(Instant.now().minusSeconds(1)),
                run.getId());
        assertThat(runs.expireStaleRun(run.getId(), Instant.now())).isTrue();
        assertThat(runs.require(user, run.getId()).getStatus()).isEqualTo(RunStatus.FAILED);
    }

    @Test
    void switchingModelAndCreatingRunCannotProduceAMixedModelSelection() throws Exception {
        stubConfiguredModels();
        String suffix = UUID.randomUUID().toString().substring(0, 8);
        UserAccount user = authService.register("model-race-" + suffix, "password-1234").user();
        Conversation conversation = conversations.create(user, "模型竞争", null, ConversationMode.CHAT);
        CountDownLatch ready = new CountDownLatch(2);
        CountDownLatch start = new CountDownLatch(1);
        ExecutorService executor = Executors.newFixedThreadPool(2);
        try {
            Future<Object> selected = executor.submit(() -> {
                ready.countDown();
                start.await();
                try {
                    return conversations.selectModel(user, conversation.getId(), ConversationModelProvider.REMOTE);
                } catch (ApiException exception) {
                    return exception;
                }
            });
            Future<Object> created = executor.submit(() -> {
                ready.countDown();
                start.await();
                try {
                    return runs.create(
                            user,
                            conversation.getId(),
                            "模型竞争任务",
                            ConversationMode.CHAT,
                            null,
                            "auto",
                            8,
                            "model-race-key-" + suffix,
                            "model-race-trace-" + suffix);
                } catch (ApiException exception) {
                    return exception;
                }
            });
            assertThat(ready.await(5, TimeUnit.SECONDS)).isTrue();
            start.countDown();
            Object selectionResult = selected.get(10, TimeUnit.SECONDS);
            Object creationResult = created.get(10, TimeUnit.SECONDS);
            Conversation current = conversations.require(user, conversation.getId());

            if (creationResult instanceof AgentRunService.CreateResult result) {
                assertThat(result.run().getModelProvider()).isEqualTo(current.getModelProvider().apiValue());
                runs.cancel(user, result.run().getId());
            } else {
                assertThat(creationResult).isInstanceOf(ApiException.class);
            }
            if (selectionResult instanceof ApiException exception) {
                assertThat(exception.getCode()).isEqualTo("CONVERSATION_HAS_ACTIVE_RUN");
            }
        } finally {
            start.countDown();
            executor.shutdownNow();
        }
    }

    @Test
    void cancelAndCompleteRaceEndsInExactlyOneTerminalState() throws Exception {
        String suffix = UUID.randomUUID().toString().substring(0, 8);
        UserAccount user = authService.register("terminal-race-" + suffix, "password-1234").user();
        Conversation conversation = conversations.create(user, "终态竞争", null, ConversationMode.CHAT);
        AgentRun run = runs.create(
                user,
                conversation.getId(),
                "并发结束",
                ConversationMode.CHAT,
                null,
                "auto",
                8,
                "terminal-key-" + suffix,
                "terminal-trace-" + suffix).run();
        String token = UUID.randomUUID().toString();
        assertThat(runs.claimDispatch(run.getId(), token)).isTrue();
        assertThat(runs.prepare(run.getId(), token, "terminal-worker")).isPresent();
        AgentServiceClient.ExecutionResponse response = executionResponse("完成", List.of());
        CountDownLatch ready = new CountDownLatch(2);
        CountDownLatch start = new CountDownLatch(1);
        ExecutorService executor = Executors.newFixedThreadPool(2);
        try {
            Future<?> completed = executor.submit(() -> {
                ready.countDown();
                start.await();
                runs.complete(run.getId(), response);
                return null;
            });
            Future<?> cancelled = executor.submit(() -> {
                ready.countDown();
                start.await();
                runs.cancel(user, run.getId());
                return null;
            });
            ready.await();
            start.countDown();
            completed.get();
            cancelled.get();
        } finally {
            executor.shutdownNow();
        }

        AgentRun terminal = runs.require(user, run.getId());
        assertThat(terminal.getStatus()).isIn(RunStatus.SUCCEEDED, RunStatus.CANCELLED);
        long terminalEvents = runEvents.findAllByRunIdOrderByIdAsc(run.getId()).stream()
                .filter(event -> event.getEventType().equals("run.succeeded")
                        || event.getEventType().equals("run.cancelled"))
                .count();
        assertThat(terminalEvents).isEqualTo(1);
    }

    @Test
    void applyingAProposalIsClaimedBeforeTheWorkspaceWriteAndIsIdempotent() throws Exception {
        String suffix = UUID.randomUUID().toString().substring(0, 8);
        UserAccount user = authService.register("apply-owner-" + suffix, "password-1234").user();
        String workspaceRoot = "/workspace/apply-" + suffix;
        when(agentService.openWorkspace(anyString(), any(UUID.class))).thenReturn(Map.of(
                "workspace",
                Map.of("root", workspaceRoot, "name", "apply-test", "tree", List.of())));
        ProjectService.OpenProjectResult opened = projects.open(user, workspaceRoot);
        Conversation conversation = conversations.create(
                user,
                "应用修改竞争",
                opened.project().getId(),
                ConversationMode.PROJECT);
        AgentRun run = runs.create(
                user,
                conversation.getId(),
                "修改文件",
                ConversationMode.PROJECT,
                opened.project().getId(),
                "confirm",
                8,
                "apply-key-" + suffix,
                "apply-trace-" + suffix).run();
        String dispatchToken = UUID.randomUUID().toString();
        assertThat(runs.claimDispatch(run.getId(), dispatchToken)).isTrue();
        assertThat(runs.prepare(run.getId(), dispatchToken, "apply-worker")).isPresent();
        List<Map<String, Object>> proposals = List.of(Map.of(
                "path", "app.py",
                "original_sha256", "a".repeat(64),
                "content", "print('new')\n",
                "diff", "-old\n+new"));
        runs.complete(run.getId(), executionResponse("修改已准备", proposals));

        CountDownLatch enteredPython = new CountDownLatch(1);
        CountDownLatch releasePython = new CountDownLatch(1);
        when(agentService.applyWorkspaceChanges(anyString(), anyList(), any(UUID.class), any(UUID.class)))
                .thenAnswer(invocation -> {
                    enteredPython.countDown();
                    if (!releasePython.await(5, TimeUnit.SECONDS)) {
                        throw new AssertionError("workspace write was not released");
                    }
                    return List.of("app.py");
                });
        ExecutorService executor = Executors.newSingleThreadExecutor();
        try {
            Future<AgentRun> firstApply = executor.submit(() -> workspaceChanges.apply(user, run.getId()));
            assertThat(enteredPython.await(5, TimeUnit.SECONDS)).isTrue();

            assertThatThrownBy(() -> workspaceChanges.apply(user, run.getId()))
                    .isInstanceOfSatisfying(ApiException.class, exception ->
                            assertThat(exception.getCode()).isEqualTo("CHANGES_ALREADY_APPLYING"));
            assertThatThrownBy(() -> runs.rejectProposedChanges(user, run.getId()))
                    .isInstanceOfSatisfying(ApiException.class, exception ->
                            assertThat(exception.getCode()).isEqualTo("NO_PROPOSED_CHANGES"));

            releasePython.countDown();
            assertThat(firstApply.get(5, TimeUnit.SECONDS).getChangeStatus()).isEqualTo("APPLIED");
            assertThat(workspaceChanges.apply(user, run.getId()).getChangeStatus()).isEqualTo("APPLIED");
            verify(agentService, times(1))
                    .applyWorkspaceChanges(anyString(), anyList(), any(UUID.class), any(UUID.class));
        } finally {
            releasePython.countDown();
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
    void sseReconnectReplaysMoreThanFiveHundredEventsWithoutGaps() throws Exception {
        String suffix = UUID.randomUUID().toString().substring(0, 8);
        UserAccount user = authService.register("sse-long-" + suffix, "password-1234").user();
        Conversation conversation = conversations.create(user, "长 SSE 重连", null, ConversationMode.CHAT);
        AgentRun run = runs.create(
                user,
                conversation.getId(),
                "测试长事件历史",
                ConversationMode.CHAT,
                null,
                "auto",
                8,
                "sse-long-key-" + suffix,
                "sse-long-trace-" + suffix).run();
        jdbcTemplate.update(
                """
                insert into run_events(run_id, event_type, payload_json, created_at)
                select ?, 'agent.progress', '{}', now()
                from generate_series(1, 510)
                """,
                run.getId());
        runs.cancel(user, run.getId());
        Long finalEventId = jdbcTemplate.queryForObject(
                "select max(id) from run_events where run_id = ?",
                Long.class,
                run.getId());

        MvcResult stream = mockMvc.perform(get("/api/v1/runs/{runId}/events", run.getId())
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

        assertThat(body).contains("id:" + finalEventId, "event:run.cancelled");
        assertThat(body.split("event:", -1).length - 1).isEqualTo(512);
    }

    @Test
    void projectListSerializesAfterTheReadOnlyTransactionCloses() throws Exception {
        String suffix = UUID.randomUUID().toString().substring(0, 8);
        UserAccount owner = authService.register("project-list-owner-" + suffix, "password-1234").user();
        UserAccount member = authService.register("project-list-member-" + suffix, "password-1234").user();
        String workspaceRoot = "/workspace/project-list-" + suffix;
        when(agentService.openWorkspace(anyString(), any(UUID.class))).thenReturn(Map.of(
                "workspace",
                Map.of("root", workspaceRoot, "name", "project-list", "tree", List.of())));

        ProjectService.OpenProjectResult opened = projects.open(owner, workspaceRoot);
        projects.addMember(opened.project().getId(), owner, member.getUsername());

        mockMvc.perform(get("/api/v1/projects")
                        .with(jwt().jwt(token -> token
                                .subject(owner.getId().toString())
                                .claim("role", "USER"))))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.projects[0].id").value(opened.project().getId().toString()))
                .andExpect(jsonPath("$.projects[0].name").value("project-list"))
                .andExpect(jsonPath("$.projects[0].workspace_root").value(workspaceRoot))
                .andExpect(jsonPath("$.projects[0].owner_id").value(owner.getId().toString()));

        mockMvc.perform(get("/api/v1/projects/{projectId}/members", opened.project().getId())
                        .with(jwt().jwt(token -> token
                                .subject(owner.getId().toString())
                                .claim("role", "USER"))))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.members.length()").value(2))
                .andExpect(jsonPath("$.members[0].username").value(owner.getUsername()))
                .andExpect(jsonPath("$.members[1].username").value(member.getUsername()));
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
    void concurrentProjectOpenAndMemberAdditionUseDatabaseUpserts() throws Exception {
        String suffix = UUID.randomUUID().toString().substring(0, 8);
        UserAccount owner = authService.register("upsert-owner-" + suffix, "password-1234").user();
        UserAccount member = authService.register("upsert-member-" + suffix, "password-1234").user();
        String root = "/workspace/upsert-" + suffix;
        when(agentService.openWorkspace(anyString(), any(UUID.class))).thenReturn(Map.of(
                "workspace",
                Map.of("root", root, "name", "upsert", "tree", List.of())));
        CountDownLatch ready = new CountDownLatch(2);
        CountDownLatch start = new CountDownLatch(1);
        ExecutorService executor = Executors.newFixedThreadPool(2);
        try {
            List<Future<ProjectService.OpenProjectResult>> opened = java.util.stream.IntStream.range(0, 2)
                    .mapToObj(index -> executor.submit(() -> {
                        ready.countDown();
                        start.await();
                        return projects.open(owner, root);
                    }))
                    .toList();
            assertThat(ready.await(5, TimeUnit.SECONDS)).isTrue();
            start.countDown();
            UUID firstId = opened.get(0).get(10, TimeUnit.SECONDS).project().getId();
            UUID secondId = opened.get(1).get(10, TimeUnit.SECONDS).project().getId();

            assertThat(secondId).isEqualTo(firstId);
            assertThat(jdbcTemplate.queryForObject(
                    "select count(*) from projects where owner_id = ? and workspace_root = ?",
                    Integer.class,
                    owner.getId(),
                    root)).isEqualTo(1);
            assertThat(jdbcTemplate.queryForObject(
                    "select count(*) from project_members where project_id = ? and user_id = ?",
                    Integer.class,
                    firstId,
                    owner.getId())).isEqualTo(1);

            CountDownLatch memberReady = new CountDownLatch(2);
            CountDownLatch memberStart = new CountDownLatch(1);
            List<Future<Object>> additions = java.util.stream.IntStream.range(0, 2)
                    .mapToObj(index -> executor.submit(() -> {
                        memberReady.countDown();
                        memberStart.await();
                        return (Object) projects.addMember(firstId, owner, member.getUsername());
                    }))
                    .toList();
            assertThat(memberReady.await(5, TimeUnit.SECONDS)).isTrue();
            memberStart.countDown();
            additions.get(0).get(10, TimeUnit.SECONDS);
            additions.get(1).get(10, TimeUnit.SECONDS);
            assertThat(jdbcTemplate.queryForObject(
                    "select count(*) from project_members where project_id = ? and user_id = ?",
                    Integer.class,
                    firstId,
                    member.getId())).isEqualTo(1);
        } finally {
            start.countDown();
            executor.shutdownNow();
        }
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
    void qqMailMcpConnectionIsUserScopedAndNeverReturnsTheAuthorizationCode() throws Exception {
        String suffix = UUID.randomUUID().toString().substring(0, 8);
        UserAccount user = authService.register("mcp-mail-" + suffix, "password-1234").user();
        UserAccount other = authService.register("mcp-other-" + suffix, "password-1234").user();
        when(agentService.testQqMail(any(AgentServiceClient.QqMailTestRequest.class)))
                .thenReturn(new AgentServiceClient.QqMailTestResponse(
                        true,
                        12,
                        List.of(
                                "qq_mail_list_folders",
                                "qq_mail_list_messages",
                                "qq_mail_search_messages",
                                "qq_mail_read_message")));

        MvcResult connected = mockMvc.perform(put("/api/v1/mcp/servers/qq-mail")
                        .with(jwt().jwt(token -> token
                                .subject(user.getId().toString())
                                .claim("role", "USER")))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"email":"123456789@qq.com","authorization_code":"qq-mail-auth-code"}
                                """))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.server.kind").value("qq_mail"))
                .andExpect(jsonPath("$.server.account").value("12****@qq.com"))
                .andExpect(jsonPath("$.server.credential_configured").value(true))
                .andExpect(jsonPath("$.server.authorization_code").doesNotExist())
                .andExpect(jsonPath("$.server.tools.length()").value(4))
                .andReturn();

        String serverId = com.jayway.jsonpath.JsonPath.read(
                connected.getResponse().getContentAsString(),
                "$.server.id");
        String encrypted = jdbcTemplate.queryForObject(
                "select encrypted_secret from mcp_server_connections where id = ?",
                String.class,
                UUID.fromString(serverId));
        assertThat(encrypted).startsWith("v1.").doesNotContain("qq-mail-auth-code");
        assertThat(mcpServers.executionConfigs(user.getId()))
                .singleElement()
                .satisfies(config -> {
                    assertThat(config.kind()).isEqualTo("qq_mail");
                    assertThat(config.config()).containsEntry("email", "123456789@qq.com");
                    assertThat(config.credentials()).containsEntry("authorization_code", "qq-mail-auth-code");
                });

        mockMvc.perform(get("/api/v1/mcp/servers")
                        .with(jwt().jwt(token -> token
                                .subject(other.getId().toString())
                                .claim("role", "USER"))))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.servers.length()").value(0));

        mockMvc.perform(put("/api/v1/mcp/servers/{id}/enabled", serverId)
                        .with(jwt().jwt(token -> token
                                .subject(user.getId().toString())
                                .claim("role", "USER")))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"enabled\":false}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.server.enabled").value(false));
        assertThat(mcpServers.executionConfigs(user.getId())).isEmpty();

        mockMvc.perform(delete("/api/v1/mcp/servers/{id}", serverId)
                        .with(jwt().jwt(token -> token
                                .subject(user.getId().toString())
                                .claim("role", "USER"))))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.ok").value(true));
        assertThat(jdbcTemplate.queryForObject(
                "select count(*) from mcp_server_connections where id = ?",
                Integer.class,
                UUID.fromString(serverId))).isZero();
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
    void conversationSelectsASpecificRegisteredLocalModel() throws Exception {
        String suffix = UUID.randomUUID().toString().substring(0, 8);
        UserAccount user = authService.register("specific-model-" + suffix, "password-1234").user();
        Conversation conversation = conversations.create(user, "具体模型", null, ConversationMode.CHAT);
        when(agentService.registeredModels()).thenReturn(Map.of("models", List.of(
                Map.of(
                        "id", "local:minimind-64m",
                        "provider", "local",
                        "display_name", "MiniMind 64M",
                        "model_name", "minimind",
                        "source", "manifest",
                        "available", true,
                        "installed", true),
                Map.of(
                        "id", "local:minimind-94m",
                        "provider", "local",
                        "display_name", "MiniMind 94M",
                        "model_name", "minimind-94m",
                        "source", "manifest",
                        "available", true,
                        "installed", true))));

        mockMvc.perform(put("/api/v1/conversations/{conversationId}/model", conversation.getId())
                        .with(jwt().jwt(token -> token
                                .subject(user.getId().toString())
                                .claim("role", "USER")))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"model_id":"local:minimind-94m"}
                                """))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.conversation.model_provider").value("local"))
                .andExpect(jsonPath("$.conversation.model_id").value("local:minimind-94m"));

        Conversation selected = conversations.require(user, conversation.getId());
        assertThat(selected.getModelId()).isEqualTo("local:minimind-94m");
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

    @Test
    void deepSeekQuotaCannotBeOverspentByConcurrentRequests() throws Exception {
        int previousLimit = properties.getSecurity().getDeepseekRunsPerDay();
        properties.getSecurity().setDeepseekRunsPerDay(2);
        String suffix = UUID.randomUUID().toString().substring(0, 8);
        UserAccount user = authService.register("quota-race-" + suffix, "password-1234").user();
        int contenders = 8;
        CountDownLatch ready = new CountDownLatch(contenders);
        CountDownLatch start = new CountDownLatch(1);
        ExecutorService executor = Executors.newFixedThreadPool(contenders);
        try {
            List<Future<Object>> attempts = java.util.stream.IntStream.range(0, contenders)
                    .mapToObj(index -> executor.<Object>submit(() -> {
                        ready.countDown();
                        start.await();
                        try {
                            deepSeekQuotas.consume(user.getId());
                            return "consumed";
                        } catch (ApiException exception) {
                            return exception;
                        }
                    }))
                    .toList();
            assertThat(ready.await(5, TimeUnit.SECONDS)).isTrue();
            start.countDown();
            List<Object> results = attempts.stream().map(future -> {
                try {
                    return future.get(10, TimeUnit.SECONDS);
                } catch (Exception exception) {
                    throw new AssertionError(exception);
                }
            }).toList();

            assertThat(results.stream().filter("consumed"::equals).count()).isEqualTo(2);
            assertThat(results.stream().filter(ApiException.class::isInstance).count()).isEqualTo(6);
            assertThat(deepSeekQuotas.snapshot(user.getId()).used()).isEqualTo(2);
        } finally {
            start.countDown();
            executor.shutdownNow();
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

    private AgentServiceClient.ExecutionResponse executionResponse(
            String finalAnswer,
            List<Map<String, Object>> proposedChanges) {
        return new AgentServiceClient.ExecutionResponse(
                finalAnswer,
                1,
                List.of(),
                proposedChanges,
                "trace-integration",
                "local",
                "minimind",
                1,
                10L,
                2L,
                5L);
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
