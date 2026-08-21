package com.aioagent.business.conversation;

import java.util.List;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;

public interface MessageRepository extends JpaRepository<Message, UUID> {
    List<Message> findAllByConversationIdOrderByCreatedAtAscIdAsc(UUID conversationId);

    Page<Message> findAllByConversationIdOrderByCreatedAtDescIdDesc(UUID conversationId, Pageable pageable);

    long countByConversationId(UUID conversationId);
}
