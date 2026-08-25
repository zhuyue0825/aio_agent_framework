package com.aioagent.business.project;

import com.aioagent.business.agent.AgentServiceClient;
import com.aioagent.business.auth.UserAccount;
import com.aioagent.business.auth.UserRepository;
import com.aioagent.business.common.ApiException;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.time.Instant;
import java.sql.Timestamp;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionTemplate;

@Service
public class ProjectService {

    private final ProjectRepository projects;
    private final ProjectMemberRepository members;
    private final UserRepository users;
    private final AgentServiceClient agentService;
    private final JdbcTemplate database;
    private final TransactionTemplate transaction;

    public ProjectService(
            ProjectRepository projects,
            ProjectMemberRepository members,
            UserRepository users,
            AgentServiceClient agentService,
            JdbcTemplate database,
            TransactionTemplate transaction) {
        this.projects = projects;
        this.members = members;
        this.users = users;
        this.agentService = agentService;
        this.database = database;
        this.transaction = transaction;
    }

    public OpenProjectResult open(UserAccount user, String requestedPath) {
        Map<String, Object> response = agentService.openWorkspace(requestedPath, user.getId());
        Map<String, Object> workspace = workspaceFrom(response);
        String root = requiredString(workspace, "root");
        String name = requiredString(workspace, "name");
        Project project = transaction.execute(status -> openTransactional(user, name, root));
        if (project == null) {
            throw new IllegalStateException("Project transaction returned no result");
        }
        return new OpenProjectResult(project, workspace);
    }

    private Project openTransactional(UserAccount user, String name, String root) {
        UUID candidateId = UUID.randomUUID();
        Timestamp now = Timestamp.from(Instant.now());
        database.update(
                """
                insert into projects(id, owner_id, name, workspace_root, created_at, updated_at)
                values (?, ?, ?, ?, ?, ?)
                on conflict (owner_id, workspace_root) do nothing
                """,
                candidateId,
                user.getId(),
                name,
                root,
                now,
                now);
        Project project = projects.findByOwnerIdAndWorkspaceRoot(user.getId(), root)
                .orElseThrow(() -> new IllegalStateException("Project upsert did not create or find a row"));
        database.update(
                """
                insert into project_members(id, project_id, user_id, member_role, created_at)
                values (?, ?, ?, 'OWNER', ?)
                on conflict (project_id, user_id) do nothing
                """,
                UUID.randomUUID(),
                project.getId(),
                user.getId(),
                now);
        return project;
    }

    @Transactional(readOnly = true)
    public List<Project> list(UserAccount user) {
        return members.findAllByUserIdOrderByCreatedAtDesc(user.getId()).stream()
                .map(ProjectMember::getProject)
                .toList();
    }

    @Transactional(readOnly = true)
    public Project requireMember(UUID projectId, UserAccount user) {
        if (!members.existsByProjectIdAndUserId(projectId, user.getId())) {
            throw new ApiException(HttpStatus.NOT_FOUND, "PROJECT_NOT_FOUND", "项目不存在或无访问权限");
        }
        return projects.findById(projectId)
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "PROJECT_NOT_FOUND", "项目不存在"));
    }

    @Transactional
    public ProjectMember addMember(UUID projectId, UserAccount actor, String username) {
        Project project = requireOwner(projectId, actor);
        UserAccount target = users.findByUsernameIgnoreCase(username.trim())
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "USER_NOT_FOUND", "用户不存在"));
        database.update(
                """
                insert into project_members(id, project_id, user_id, member_role, created_at)
                values (?, ?, ?, 'MEMBER', ?)
                on conflict (project_id, user_id) do nothing
                """,
                UUID.randomUUID(),
                project.getId(),
                target.getId(),
                Timestamp.from(Instant.now()));
        return members.findByProjectIdAndUserId(projectId, target.getId())
                .orElseThrow(() -> new IllegalStateException("Project member upsert did not create or find a row"));
    }

    @Transactional(readOnly = true)
    public List<ProjectMember> listMembers(UUID projectId, UserAccount actor) {
        requireMember(projectId, actor);
        return members.findAllByProjectIdOrderByCreatedAtAsc(projectId);
    }

    private Project requireOwner(UUID projectId, UserAccount user) {
        Project project = requireMember(projectId, user);
        if (!project.getOwner().getId().equals(user.getId())) {
            throw new ApiException(HttpStatus.FORBIDDEN, "PROJECT_OWNER_REQUIRED", "只有项目所有者可以管理成员");
        }
        return project;
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> workspaceFrom(Map<String, Object> response) {
        Object workspace = response == null ? null : response.get("workspace");
        if (!(workspace instanceof Map<?, ?> map)) {
            throw new ApiException(HttpStatus.BAD_GATEWAY, "INVALID_AGENT_RESPONSE", "Agent 服务返回了无效工作区数据");
        }
        return (Map<String, Object>) map;
    }

    private String requiredString(Map<String, Object> data, String key) {
        Object value = data.get(key);
        if (!(value instanceof String text) || text.isBlank()) {
            throw new ApiException(HttpStatus.BAD_GATEWAY, "INVALID_AGENT_RESPONSE", "工作区缺少字段: " + key);
        }
        return text;
    }

    public record OpenProjectResult(Project project, Map<String, Object> workspace) {
    }
}
