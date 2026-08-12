package com.aioagent.business.conversation;

import com.aioagent.business.auth.UserAccount;
import com.aioagent.business.common.ApiException;
import com.aioagent.business.project.Project;
import com.aioagent.business.project.ProjectService;
import com.aioagent.business.run.AgentRunRepository;
import com.aioagent.business.run.RunStatus;
import java.util.List;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class ConversationService {

    private static final List<RunStatus> ACTIVE_STATUSES = List.of(RunStatus.PENDING, RunStatus.RUNNING);
    private final ConversationRepository conversations;
    private final MessageRepository messages;
    private final AgentRunRepository runs;
    private final ProjectService projectService;

    public ConversationService(
            ConversationRepository conversations,
            MessageRepository messages,
            AgentRunRepository runs,
            ProjectService projectService) {
        this.conversations = conversations;
        this.messages = messages;
        this.runs = runs;
        this.projectService = projectService;
    }

    @Transactional
    public List<Conversation> listOrCreate(UserAccount user) {
        List<Conversation> result = conversations.findAllByOwnerIdOrderByUpdatedAtDesc(user.getId());
        if (result.isEmpty()) {
            result = List.of(conversations.save(new Conversation(user, null, "新对话", ConversationMode.CHAT)));
        }
        return result;
    }

    @Transactional
    public Conversation create(UserAccount user, String title, UUID projectId, ConversationMode mode) {
        Project project = null;
        if (projectId != null) {
            project = projectService.requireMember(projectId, user);
            mode = ConversationMode.PROJECT;
        }
        return conversations.save(new Conversation(user, project, normalizedTitle(title), mode));
    }

    @Transactional
    public Conversation rename(UserAccount user, UUID conversationId, String title) {
        Conversation conversation = require(user, conversationId);
        conversation.rename(normalizedTitle(title));
        return conversation;
    }

    @Transactional
    public void delete(UserAccount user, UUID conversationId) {
        Conversation conversation = require(user, conversationId);
        if (runs.existsByConversationIdAndStatusIn(conversationId, ACTIVE_STATUSES)) {
            throw new ApiException(HttpStatus.CONFLICT, "CONVERSATION_HAS_ACTIVE_RUN", "运行中的会话不能删除");
        }
        conversations.delete(conversation);
    }

    @Transactional(readOnly = true)
    public Conversation require(UserAccount user, UUID conversationId) {
        return conversations.findByIdAndOwnerId(conversationId, user.getId())
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "CONVERSATION_NOT_FOUND", "会话不存在"));
    }

    @Transactional(readOnly = true)
    public List<Message> listMessages(UserAccount user, UUID conversationId) {
        require(user, conversationId);
        return messages.findAllByConversationIdOrderByCreatedAtAscIdAsc(conversationId);
    }

    public long messageCount(UUID conversationId) {
        return messages.countByConversationId(conversationId);
    }

    private String normalizedTitle(String title) {
        String value = title == null ? "新对话" : title.trim();
        return value.isEmpty() ? "新对话" : value.substring(0, Math.min(value.length(), 80));
    }
}
