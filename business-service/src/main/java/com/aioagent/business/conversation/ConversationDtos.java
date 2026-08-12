package com.aioagent.business.conversation;

import java.time.Instant;
import java.util.Map;
import java.util.UUID;
import tools.jackson.core.JacksonException;
import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.ObjectMapper;

public final class ConversationDtos {

    private static final TypeReference<Map<String, Object>> MAP_TYPE = new TypeReference<>() {
    };

    private ConversationDtos() {
    }

    public record ConversationResponse(
            UUID id,
            String title,
            String mode,
            UUID projectId,
            Instant createdAt,
            Instant updatedAt,
            long messageCount) {
        public static ConversationResponse from(Conversation conversation, long messageCount) {
            return new ConversationResponse(
                    conversation.getId(),
                    conversation.getTitle(),
                    conversation.getMode().name().toLowerCase(),
                    conversation.getProject() == null ? null : conversation.getProject().getId(),
                    conversation.getCreatedAt(),
                    conversation.getUpdatedAt(),
                    messageCount);
        }
    }

    public record MessageResponse(
            UUID id,
            UUID conversationId,
            String role,
            String content,
            Map<String, Object> metadata,
            Instant createdAt) {
        public static MessageResponse from(Message message, ObjectMapper mapper) {
            return new MessageResponse(
                    message.getId(),
                    message.getConversation().getId(),
                    message.getRole().name().toLowerCase(),
                    message.getContent(),
                    parseMetadata(message.getMetadataJson(), mapper),
                    message.getCreatedAt());
        }
    }

    private static Map<String, Object> parseMetadata(String json, ObjectMapper mapper) {
        try {
            return mapper.readValue(json, MAP_TYPE);
        } catch (JacksonException exception) {
            return Map.of();
        }
    }
}
