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
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.data.domain.Page;
import java.util.LinkedHashMap;
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
    public Map<String, Object> list(
            @RequestParam(defaultValue = "0") @jakarta.validation.constraints.Min(0) int page,
            @RequestParam(defaultValue = "50") @jakarta.validation.constraints.Min(1)
                    @jakarta.validation.constraints.Max(100) int size,
            Authentication authentication) {
        UserAccount user = currentUser.require(authentication);
        Page<Conversation> conversationPage = service.listOrCreate(user, page, size);
        List<ConversationDtos.ConversationResponse> result = conversationPage.getContent().stream()
                .map(conversation -> ConversationDtos.ConversationResponse.from(
                        conversation,
                        service.messageCount(conversation.getId())))
                .toList();
        Map<String, Object> response = new LinkedHashMap<>();
        response.put("conversations", result);
        response.put("page", page);
        response.put("size", size);
        response.put("total", conversationPage.getTotalElements());
        response.put("has_more", conversationPage.hasNext());
        return response;
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
    public Map<String, Object> messages(
            @PathVariable UUID conversationId,
            @RequestParam(defaultValue = "0") @jakarta.validation.constraints.Min(0) int page,
            @RequestParam(defaultValue = "100") @jakarta.validation.constraints.Min(1)
                    @jakarta.validation.constraints.Max(200) int size,
            Authentication authentication) {
        Page<Message> messagePage = service.listRecentMessages(
                currentUser.require(authentication), conversationId, page, size);
        List<ConversationDtos.MessageResponse> result = new java.util.ArrayList<>(messagePage.getContent().stream()
                .map(message -> ConversationDtos.MessageResponse.from(message, mapper))
                .toList());
        java.util.Collections.reverse(result);
        return Map.of(
                "messages", result,
                "page", page,
                "size", size,
                "has_more", messagePage.hasNext());
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
