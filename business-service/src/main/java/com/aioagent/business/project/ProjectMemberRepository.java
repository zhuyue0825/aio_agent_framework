package com.aioagent.business.project;

import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.springframework.data.jpa.repository.EntityGraph;
import org.springframework.data.jpa.repository.JpaRepository;

public interface ProjectMemberRepository extends JpaRepository<ProjectMember, UUID> {
    @EntityGraph(attributePaths = "user")
    Optional<ProjectMember> findByProjectIdAndUserId(UUID projectId, UUID userId);

    boolean existsByProjectIdAndUserId(UUID projectId, UUID userId);

    @EntityGraph(attributePaths = {"project", "project.owner"})
    List<ProjectMember> findAllByUserIdOrderByCreatedAtDesc(UUID userId);

    @EntityGraph(attributePaths = "user")
    List<ProjectMember> findAllByProjectIdOrderByCreatedAtAsc(UUID projectId);
}
