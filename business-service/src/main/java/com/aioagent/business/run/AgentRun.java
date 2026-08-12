package com.aioagent.business.run;

import com.aioagent.business.auth.UserAccount;
import com.aioagent.business.conversation.Conversation;
import com.aioagent.business.conversation.ConversationMode;
import com.aioagent.business.conversation.Message;
import com.aioagent.business.project.Project;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.FetchType;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.Table;
import jakarta.persistence.Version;
import java.time.Instant;
import java.util.UUID;

@Entity
@Table(name = "agent_runs")
public class AgentRun {

    @Id
    @GeneratedValue(strategy = GenerationType.UUID)
    private UUID id;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "conversation_id", nullable = false)
    private Conversation conversation;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "user_message_id", nullable = false)
    private Message userMessage;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "project_id")
    private Project project;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "requested_by_id", nullable = false)
    private UserAccount requestedBy;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 20)
    private RunStatus status;

    @Column(nullable = false, columnDefinition = "text")
    private String task;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 20)
    private ConversationMode mode;

    @Column(name = "approval_mode", nullable = false, length = 20)
    private String approvalMode;

    @Column(name = "max_history_messages", nullable = false)
    private int maxHistoryMessages;

    @Column(name = "idempotency_key", nullable = false, length = 100)
    private String idempotencyKey;

    @Column(name = "trace_id", nullable = false, length = 100)
    private String traceId;

    @Column(name = "final_answer", columnDefinition = "text")
    private String finalAnswer;

    private Integer steps;

    @Column(name = "changed_files_json", nullable = false, columnDefinition = "text")
    private String changedFilesJson;

    @Column(name = "error_code", length = 80)
    private String errorCode;

    @Column(name = "error_message", columnDefinition = "text")
    private String errorMessage;

    @Column(name = "cancel_requested", nullable = false)
    private boolean cancelRequested;

    @Column(name = "created_at", nullable = false)
    private Instant createdAt;

    @Column(name = "started_at")
    private Instant startedAt;

    @Column(name = "finished_at")
    private Instant finishedAt;

    @Version
    @Column(nullable = false)
    private long version;

    protected AgentRun() {
    }

    public AgentRun(
            Conversation conversation,
            Message userMessage,
            Project project,
            UserAccount requestedBy,
            String task,
            ConversationMode mode,
            String approvalMode,
            int maxHistoryMessages,
            String idempotencyKey,
            String traceId) {
        this.conversation = conversation;
        this.userMessage = userMessage;
        this.project = project;
        this.requestedBy = requestedBy;
        this.status = RunStatus.PENDING;
        this.task = task;
        this.mode = mode;
        this.approvalMode = approvalMode;
        this.maxHistoryMessages = maxHistoryMessages;
        this.idempotencyKey = idempotencyKey;
        this.traceId = traceId;
        this.changedFilesJson = "[]";
        this.createdAt = Instant.now();
    }

    public void markRunning() {
        if (status != RunStatus.PENDING) {
            throw new IllegalStateException("Only a pending run can start");
        }
        this.status = RunStatus.RUNNING;
        this.startedAt = Instant.now();
    }

    public void markSucceeded(String finalAnswer, int steps, String changedFilesJson) {
        if (status != RunStatus.RUNNING) {
            return;
        }
        this.status = RunStatus.SUCCEEDED;
        this.finalAnswer = finalAnswer;
        this.steps = steps;
        this.changedFilesJson = changedFilesJson;
        this.finishedAt = Instant.now();
    }

    public void markFailed(RunStatus failureStatus, String errorCode, String errorMessage) {
        if (status.isTerminal()) {
            return;
        }
        if (failureStatus != RunStatus.FAILED && failureStatus != RunStatus.TIMED_OUT) {
            throw new IllegalArgumentException("Unsupported failure status");
        }
        this.status = failureStatus;
        this.errorCode = errorCode;
        this.errorMessage = errorMessage;
        this.finishedAt = Instant.now();
    }

    public void cancel() {
        if (status.isTerminal()) {
            return;
        }
        this.cancelRequested = true;
        this.status = RunStatus.CANCELLED;
        this.finishedAt = Instant.now();
    }

    public UUID getId() {
        return id;
    }

    public Conversation getConversation() {
        return conversation;
    }

    public Message getUserMessage() {
        return userMessage;
    }

    public Project getProject() {
        return project;
    }

    public UserAccount getRequestedBy() {
        return requestedBy;
    }

    public RunStatus getStatus() {
        return status;
    }

    public String getTask() {
        return task;
    }

    public ConversationMode getMode() {
        return mode;
    }

    public String getApprovalMode() {
        return approvalMode;
    }

    public int getMaxHistoryMessages() {
        return maxHistoryMessages;
    }

    public String getIdempotencyKey() {
        return idempotencyKey;
    }

    public String getTraceId() {
        return traceId;
    }

    public String getFinalAnswer() {
        return finalAnswer;
    }

    public Integer getSteps() {
        return steps;
    }

    public String getChangedFilesJson() {
        return changedFilesJson;
    }

    public String getErrorCode() {
        return errorCode;
    }

    public String getErrorMessage() {
        return errorMessage;
    }

    public boolean isCancelRequested() {
        return cancelRequested;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    public Instant getStartedAt() {
        return startedAt;
    }

    public Instant getFinishedAt() {
        return finishedAt;
    }
}
