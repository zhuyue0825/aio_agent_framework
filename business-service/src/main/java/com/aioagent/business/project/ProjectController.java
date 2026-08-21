package com.aioagent.business.project;

import com.aioagent.business.agent.AgentServiceClient;
import com.aioagent.business.auth.CurrentUser;
import com.aioagent.business.auth.UserAccount;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1")
public class ProjectController {

    private final CurrentUser currentUser;
    private final ProjectService projectService;
    private final AgentServiceClient agentService;

    public ProjectController(CurrentUser currentUser, ProjectService projectService, AgentServiceClient agentService) {
        this.currentUser = currentUser;
        this.projectService = projectService;
        this.agentService = agentService;
    }

    @GetMapping("/projects")
    public Map<String, List<ProjectDtos.ProjectResponse>> list(Authentication authentication) {
        UserAccount user = currentUser.require(authentication);
        return Map.of("projects", projectService.list(user).stream().map(ProjectDtos.ProjectResponse::from).toList());
    }

    @PostMapping("/projects/open")
    public Map<String, Object> open(@Valid @RequestBody OpenWorkspaceRequest request, Authentication authentication) {
        ProjectService.OpenProjectResult result = projectService.open(currentUser.require(authentication), request.path());
        return Map.of(
                "project", ProjectDtos.ProjectResponse.from(result.project()),
                "workspace", result.workspace());
    }

    @PostMapping("/projects/{projectId}/members")
    public Map<String, ProjectDtos.MemberResponse> addMember(
            @PathVariable UUID projectId,
            @Valid @RequestBody AddMemberRequest request,
            Authentication authentication) {
        ProjectMember member = projectService.addMember(projectId, currentUser.require(authentication), request.username());
        return Map.of("member", ProjectDtos.MemberResponse.from(member));
    }

    @GetMapping("/projects/{projectId}/members")
    public Map<String, List<ProjectDtos.MemberResponse>> listMembers(
            @PathVariable UUID projectId,
            Authentication authentication) {
        List<ProjectDtos.MemberResponse> result = projectService
                .listMembers(projectId, currentUser.require(authentication))
                .stream()
                .map(ProjectDtos.MemberResponse::from)
                .toList();
        return Map.of("members", result);
    }

    @GetMapping("/workspaces/directories")
    public Map<String, Object> directories(
            @RequestParam(required = false) String path,
            Authentication authentication) {
        currentUser.require(authentication);
        UserAccount user = currentUser.require(authentication);
        return agentService.listDirectories(path, user.getId());
    }

    @GetMapping("/projects/{projectId}/workspace/tree")
    public Map<String, Object> tree(@PathVariable UUID projectId, Authentication authentication) {
        Project project = projectService.requireMember(projectId, currentUser.require(authentication));
        return agentService.workspaceTree(project.getWorkspaceRoot(), project.getOwner().getId());
    }

    @GetMapping("/projects/{projectId}/workspace/file")
    public Map<String, Object> file(
            @PathVariable UUID projectId,
            @RequestParam String path,
            Authentication authentication) {
        Project project = projectService.requireMember(projectId, currentUser.require(authentication));
        return agentService.workspaceFile(project.getWorkspaceRoot(), path, project.getOwner().getId());
    }

    @PutMapping("/projects/{projectId}/workspace/file")
    public Map<String, Object> saveFile(
            @PathVariable UUID projectId,
            @Valid @RequestBody SaveFileRequest request,
            Authentication authentication) {
        Project project = projectService.requireMember(projectId, currentUser.require(authentication));
        return agentService.saveWorkspaceFile(
                project.getWorkspaceRoot(),
                request.path(),
                request.content(),
                project.getOwner().getId());
    }

    public record OpenWorkspaceRequest(@NotBlank String path) {
    }

    public record AddMemberRequest(@NotBlank @Size(max = 50) String username) {
    }

    public record SaveFileRequest(@NotBlank String path, String content) {
    }
}
