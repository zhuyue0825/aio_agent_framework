package com.aioagent.business.conversation;

import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;

public interface ConversationRepository extends JpaRepository<Conversation, UUID> {
    List<Conversation> findAllByOwnerIdOrderByUpdatedAtDesc(UUID ownerId);

    Page<Conversation> findAllByOwnerIdOrderByUpdatedAtDesc(UUID ownerId, Pageable pageable);

    Optional<Conversation> findByIdAndOwnerId(UUID id, UUID ownerId);
}
