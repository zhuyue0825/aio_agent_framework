package com.aioagent.business.project;

import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;

public interface ProjectMemberRepository extends JpaRepository<ProjectMember, UUID> {
    Optional<ProjectMember> findByProjectIdAndUserId(UUID projectId, UUID userId);

    boolean existsByProjectIdAndUserId(UUID projectId, UUID userId);

    List<ProjectMember> findAllByUserIdOrderByCreatedAtDesc(UUID userId);

    List<ProjectMember> findAllByProjectIdOrderByCreatedAtAsc(UUID projectId);
}
