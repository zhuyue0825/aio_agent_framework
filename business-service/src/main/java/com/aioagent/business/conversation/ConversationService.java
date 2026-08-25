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
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
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
            result = List.of(conversations.save(new Conversation(
                    user,
                    null,
                    "新对话",
                    ConversationMode.CHAT,
                    ConversationModelProvider.LOCAL,
                    ConversationModelProvider.LOCAL.defaultModelId())));
        }
        return result;
    }

    @Transactional
    public Page<Conversation> listOrCreate(UserAccount user, int page, int size) {
        Page<Conversation> result = conversations.findAllByOwnerIdOrderByUpdatedAtDesc(
                user.getId(),
                PageRequest.of(page, size));
        if (page == 0 && result.isEmpty()) {
            conversations.save(new Conversation(
                    user,
                    null,
                    "新对话",
                    ConversationMode.CHAT,
                    ConversationModelProvider.LOCAL,
                    ConversationModelProvider.LOCAL.defaultModelId()));
            result = conversations.findAllByOwnerIdOrderByUpdatedAtDesc(user.getId(), PageRequest.of(0, size));
        }
        return result;
    }

    @Transactional
    public Conversation create(UserAccount user, String title, UUID projectId, ConversationMode mode) {
        return create(user, title, projectId, mode, ConversationModelProvider.LOCAL);
    }

    @Transactional
    public Conversation create(
            UserAccount user,
            String title,
            UUID projectId,
            ConversationMode mode,
            ConversationModelProvider modelProvider) {
        return create(
                user,
                title,
                projectId,
                mode,
                modelProvider,
                modelProvider.defaultModelId());
    }

    @Transactional
    public Conversation create(
            UserAccount user,
            String title,
            UUID projectId,
            ConversationMode mode,
            ConversationModelProvider modelProvider,
            String modelId) {
        Project project = null;
        if (projectId != null) {
            project = projectService.requireMember(projectId, user);
            mode = ConversationMode.PROJECT;
        }
        return conversations.save(new Conversation(user, project, normalizedTitle(title), mode, modelProvider, modelId));
    }

    @Transactional
    public Conversation rename(UserAccount user, UUID conversationId, String title) {
        Conversation conversation = requireLocked(user, conversationId);
        conversation.rename(normalizedTitle(title));
        return conversation;
    }

    @Transactional
    public Conversation selectModel(
            UserAccount user,
            UUID conversationId,
            ConversationModelProvider modelProvider) {
        return selectModel(user, conversationId, modelProvider, modelProvider.defaultModelId());
    }

    @Transactional
    public Conversation selectModel(
            UserAccount user,
            UUID conversationId,
            ConversationModelProvider modelProvider,
            String modelId) {
        Conversation conversation = requireLocked(user, conversationId);
        if (runs.existsByConversationIdAndStatusIn(conversationId, ACTIVE_STATUSES)) {
            throw new ApiException(HttpStatus.CONFLICT, "CONVERSATION_HAS_ACTIVE_RUN", "运行期间不能切换模型");
        }
        conversation.selectModel(modelProvider, modelId);
        return conversation;
    }

    @Transactional
    public void delete(UserAccount user, UUID conversationId) {
        Conversation conversation = requireLocked(user, conversationId);
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

    @Transactional
    public Conversation requireLocked(UserAccount user, UUID conversationId) {
        return conversations.findLockedByIdAndOwnerId(conversationId, user.getId())
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "CONVERSATION_NOT_FOUND", "会话不存在"));
    }

    @Transactional
    public Conversation lock(UUID conversationId) {
        return conversations.findLockedById(conversationId)
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "CONVERSATION_NOT_FOUND", "会话不存在"));
    }

    @Transactional(readOnly = true)
    public List<Message> listMessages(UserAccount user, UUID conversationId) {
        require(user, conversationId);
        return messages.findAllByConversationIdOrderByCreatedAtAscIdAsc(conversationId);
    }

    @Transactional(readOnly = true)
    public Page<Message> listRecentMessages(UserAccount user, UUID conversationId, int page, int size) {
        require(user, conversationId);
        return messages.findAllByConversationIdOrderByCreatedAtDescIdDesc(
                conversationId,
                PageRequest.of(page, size));
    }

    public long messageCount(UUID conversationId) {
        return messages.countByConversationId(conversationId);
    }

    private String normalizedTitle(String title) {
        String value = title == null ? "新对话" : title.trim();
        return value.isEmpty() ? "新对话" : value.substring(0, Math.min(value.length(), 80));
    }
}
