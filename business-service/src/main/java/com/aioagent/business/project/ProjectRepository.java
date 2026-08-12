package com.aioagent.business.project;

import java.util.Optional;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;

public interface ProjectRepository extends JpaRepository<Project, UUID> {
    Optional<Project> findByOwnerIdAndWorkspaceRoot(UUID ownerId, String workspaceRoot);
}
