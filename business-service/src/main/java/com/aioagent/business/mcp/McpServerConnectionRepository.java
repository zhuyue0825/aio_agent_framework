package com.aioagent.business.mcp;

import jakarta.persistence.LockModeType;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface McpServerConnectionRepository extends JpaRepository<McpServerConnection, UUID> {

    List<McpServerConnection> findByOwnerIdOrderByUpdatedAtDesc(UUID ownerId);

    List<McpServerConnection> findByOwnerIdAndEnabledTrueAndStatus(
            UUID ownerId,
            McpServerStatus status);

    Optional<McpServerConnection> findByIdAndOwnerId(UUID id, UUID ownerId);

    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("""
            select connection from McpServerConnection connection
            where connection.owner.id = :ownerId and connection.kind = :kind
            """)
    Optional<McpServerConnection> findLockedByOwnerIdAndKind(
            @Param("ownerId") UUID ownerId,
            @Param("kind") McpServerKind kind);
}
