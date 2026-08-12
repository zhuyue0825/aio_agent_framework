package com.aioagent.business.run;

import java.util.Collection;
import java.util.Optional;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;

public interface AgentRunRepository extends JpaRepository<AgentRun, UUID> {
    Optional<AgentRun> findByRequestedByIdAndIdempotencyKey(UUID requestedById, String idempotencyKey);

    Optional<AgentRun> findByIdAndRequestedById(UUID id, UUID requestedById);

    boolean existsByConversationIdAndStatusIn(UUID conversationId, Collection<RunStatus> statuses);
}
