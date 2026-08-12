package com.aioagent.business.conversation;

import com.aioagent.business.auth.CurrentUser;
import com.aioagent.business.auth.UserAccount;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import tools.jackson.databind.ObjectMapper;

@RestController
@RequestMapping("/api/v1/conversations")
public class ConversationController {

    private final CurrentUser currentUser;
    private final ConversationService service;
    private final ObjectMapper mapper;

    public ConversationController(CurrentUser currentUser, ConversationService service, ObjectMapper mapper) {
        this.currentUser = currentUser;
        this.service = service;
        this.mapper = mapper;
    }

    @GetMapping
    public Map<String, List<ConversationDtos.ConversationResponse>> list(Authentication authentication) {
        UserAccount user = currentUser.require(authentication);
        List<ConversationDtos.ConversationResponse> result = service.listOrCreate(user).stream()
                .map(conversation -> ConversationDtos.ConversationResponse.from(
                        conversation,
                        service.messageCount(conversation.getId())))
                .toList();
        return Map.of("conversations", result);
    }

    @PostMapping
    public Map<String, ConversationDtos.ConversationResponse> create(
            @Valid @RequestBody CreateConversationRequest request,
            Authentication authentication) {
        UserAccount user = currentUser.require(authentication);
        Conversation conversation = service.create(
                user,
                request.title(),
                request.projectId(),
                parseMode(request.mode()));
        return Map.of("conversation", ConversationDtos.ConversationResponse.from(conversation, 0));
    }

    @PatchMapping("/{conversationId}")
    public Map<String, ConversationDtos.ConversationResponse> rename(
            @PathVariable UUID conversationId,
            @Valid @RequestBody RenameConversationRequest request,
            Authentication authentication) {
        Conversation conversation = service.rename(currentUser.require(authentication), conversationId, request.title());
        return Map.of(
                "conversation",
                ConversationDtos.ConversationResponse.from(conversation, service.messageCount(conversationId)));
    }

    @DeleteMapping("/{conversationId}")
    public Map<String, Boolean> delete(@PathVariable UUID conversationId, Authentication authentication) {
        service.delete(currentUser.require(authentication), conversationId);
        return Map.of("ok", true);
    }

    @GetMapping("/{conversationId}/messages")
    public Map<String, List<ConversationDtos.MessageResponse>> messages(
            @PathVariable UUID conversationId,
            Authentication authentication) {
        List<ConversationDtos.MessageResponse> result = service
                .listMessages(currentUser.require(authentication), conversationId)
                .stream()
                .map(message -> ConversationDtos.MessageResponse.from(message, mapper))
                .toList();
        return Map.of("messages", result);
    }

    private ConversationMode parseMode(String rawMode) {
        return "project".equalsIgnoreCase(rawMode) ? ConversationMode.PROJECT : ConversationMode.CHAT;
    }

    public record CreateConversationRequest(
            @Size(max = 80) String title,
            UUID projectId,
            @Size(max = 20) String mode) {
        public CreateConversationRequest {
            if (mode == null) {
                mode = "chat";
            }
        }
    }

    public record RenameConversationRequest(@NotBlank @Size(max = 80) String title) {
    }
}
