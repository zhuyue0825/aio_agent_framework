package com.aioagent.business.conversation;

import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;

public interface ConversationRepository extends JpaRepository<Conversation, UUID> {
    List<Conversation> findAllByOwnerIdOrderByUpdatedAtDesc(UUID ownerId);

    Optional<Conversation> findByIdAndOwnerId(UUID id, UUID ownerId);
}
