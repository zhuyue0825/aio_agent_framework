package com.aioagent.business.project;

import java.util.Optional;
import java.util.UUID;
import org.springframework.data.jpa.repository.EntityGraph;
import org.springframework.data.jpa.repository.JpaRepository;

public interface ProjectRepository extends JpaRepository<Project, UUID> {
    @EntityGraph(attributePaths = "owner")
    Optional<Project> findByOwnerIdAndWorkspaceRoot(UUID ownerId, String workspaceRoot);

    @Override
    @EntityGraph(attributePaths = "owner")
    Optional<Project> findById(UUID id);
}
