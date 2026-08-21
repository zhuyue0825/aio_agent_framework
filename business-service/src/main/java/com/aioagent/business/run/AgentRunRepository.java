package com.aioagent.business.run;

import java.util.Collection;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface AgentRunRepository extends JpaRepository<AgentRun, UUID> {
    Optional<AgentRun> findByRequestedByIdAndIdempotencyKey(UUID requestedById, String idempotencyKey);

    Optional<AgentRun> findByIdAndRequestedById(UUID id, UUID requestedById);

    boolean existsByConversationIdAndStatusIn(UUID conversationId, Collection<RunStatus> statuses);

    List<AgentRun> findAllByStatusOrderByCreatedAtAsc(RunStatus status);

    List<AgentRun> findAllByStatusAndStartedAtBeforeOrderByStartedAtAsc(RunStatus status, Instant cutoff);

    @Query("""
            select coalesce(sum(coalesce(run.inputTokens, 0) + coalesce(run.outputTokens, 0)), 0)
            from AgentRun run
            where run.requestedBy.id = :userId and run.finishedAt >= :since
            """)
    long sumTokensSince(@Param("userId") UUID userId, @Param("since") Instant since);
}
