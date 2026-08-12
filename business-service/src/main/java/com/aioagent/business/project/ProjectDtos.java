package com.aioagent.business.project;

import java.time.Instant;
import java.util.UUID;

public final class ProjectDtos {

    private ProjectDtos() {
    }

    public record ProjectResponse(
            UUID id,
            String name,
            String workspaceRoot,
            UUID ownerId,
            Instant createdAt,
            Instant updatedAt) {
        public static ProjectResponse from(Project project) {
            return new ProjectResponse(
                    project.getId(),
                    project.getName(),
                    project.getWorkspaceRoot(),
                    project.getOwner().getId(),
                    project.getCreatedAt(),
                    project.getUpdatedAt());
        }
    }

    public record MemberResponse(UUID userId, String username, ProjectMemberRole role, Instant createdAt) {
        public static MemberResponse from(ProjectMember member) {
            return new MemberResponse(
                    member.getUser().getId(),
                    member.getUser().getUsername(),
                    member.getRole(),
                    member.getCreatedAt());
        }
    }
}
