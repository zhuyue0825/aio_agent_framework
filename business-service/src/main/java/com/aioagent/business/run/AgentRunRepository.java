package com.aioagent.business.run;

import java.util.Collection;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.repository.query.Param;
import jakarta.persistence.LockModeType;

public interface AgentRunRepository extends JpaRepository<AgentRun, UUID> {
    Optional<AgentRun> findByRequestedByIdAndIdempotencyKey(UUID requestedById, String idempotencyKey);

    Optional<AgentRun> findByIdAndRequestedById(UUID id, UUID requestedById);

    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("select run from AgentRun run where run.id = :id")
    Optional<AgentRun> findLockedById(@Param("id") UUID id);

    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("select run from AgentRun run where run.id = :id and run.requestedBy.id = :userId")
    Optional<AgentRun> findLockedByIdAndRequestedById(@Param("id") UUID id, @Param("userId") UUID userId);

    boolean existsByConversationIdAndStatusIn(UUID conversationId, Collection<RunStatus> statuses);

    @Query("""
            select run from AgentRun run
            where run.status = :status
              and (run.dispatchToken is null or run.leaseExpiresAt is null or run.leaseExpiresAt < :now)
            order by run.createdAt asc
            """)
    List<AgentRun> findDispatchable(@Param("status") RunStatus status, @Param("now") Instant now);

    List<AgentRun> findAllByStatusAndLeaseExpiresAtBeforeOrderByLeaseExpiresAtAsc(
            RunStatus status, Instant cutoff);

    List<AgentRun> findAllByChangeStatusAndChangeApplyStartedAtBeforeOrderByChangeApplyStartedAtAsc(
            String changeStatus, Instant cutoff);

    @Modifying(clearAutomatically = true, flushAutomatically = true)
    @Query("""
            update AgentRun run
            set run.dispatchedAt = :now,
                run.dispatchToken = :dispatchToken,
                run.leaseExpiresAt = :leaseExpiresAt,
                run.version = run.version + 1
            where run.id = :runId
              and run.status = :status
              and (run.dispatchToken is null or run.leaseExpiresAt is null or run.leaseExpiresAt < :now)
            """)
    int claimDispatch(
            @Param("runId") UUID runId,
            @Param("status") RunStatus status,
            @Param("dispatchToken") String dispatchToken,
            @Param("now") Instant now,
            @Param("leaseExpiresAt") Instant leaseExpiresAt);

    @Modifying(clearAutomatically = true, flushAutomatically = true)
    @Query("""
            update AgentRun run
            set run.dispatchedAt = null,
                run.dispatchToken = null,
                run.leaseExpiresAt = null,
                run.version = run.version + 1
            where run.id = :runId
              and run.status = :status
              and run.dispatchToken = :dispatchToken
            """)
    int releaseDispatch(
            @Param("runId") UUID runId,
            @Param("status") RunStatus status,
            @Param("dispatchToken") String dispatchToken);

    @Query("""
            select coalesce(sum(coalesce(run.inputTokens, 0) + coalesce(run.outputTokens, 0)), 0)
            from AgentRun run
            where run.requestedBy.id = :userId and run.finishedAt >= :since
            """)
    long sumTokensSince(@Param("userId") UUID userId, @Param("since") Instant since);
}
