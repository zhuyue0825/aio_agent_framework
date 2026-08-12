package com.aioagent.business.conversation;

import java.util.List;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;

public interface MessageRepository extends JpaRepository<Message, UUID> {
    List<Message> findAllByConversationIdOrderByCreatedAtAscIdAsc(UUID conversationId);

    long countByConversationId(UUID conversationId);
}
