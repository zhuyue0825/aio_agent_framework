package com.aioagent.business.conversation;

import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import jakarta.persistence.LockModeType;

public interface ConversationRepository extends JpaRepository<Conversation, UUID> {
    List<Conversation> findAllByOwnerIdOrderByUpdatedAtDesc(UUID ownerId);

    Page<Conversation> findAllByOwnerIdOrderByUpdatedAtDesc(UUID ownerId, Pageable pageable);

    Optional<Conversation> findByIdAndOwnerId(UUID id, UUID ownerId);

    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("select conversation from Conversation conversation where conversation.id = :id")
    Optional<Conversation> findLockedById(@Param("id") UUID id);

    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("""
            select conversation from Conversation conversation
            where conversation.id = :id and conversation.owner.id = :ownerId
            """)
    Optional<Conversation> findLockedByIdAndOwnerId(@Param("id") UUID id, @Param("ownerId") UUID ownerId);
}
