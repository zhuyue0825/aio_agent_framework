package com.aioagent.business.conversation;

import com.aioagent.business.auth.UserAccount;
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
import java.time.Instant;
import java.util.UUID;

@Entity
@Table(name = "conversations")
public class Conversation {

    @Id
    @GeneratedValue(strategy = GenerationType.UUID)
    private UUID id;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "owner_id", nullable = false)
    private UserAccount owner;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "project_id")
    private Project project;

    @Column(nullable = false, length = 80)
    private String title;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 20)
    private ConversationMode mode;

    @Enumerated(EnumType.STRING)
    @Column(name = "model_provider", nullable = false, length = 20)
    private ConversationModelProvider modelProvider;

    @Column(name = "created_at", nullable = false)
    private Instant createdAt;

    @Column(name = "updated_at", nullable = false)
    private Instant updatedAt;

    protected Conversation() {
    }

    public Conversation(
            UserAccount owner,
            Project project,
            String title,
            ConversationMode mode,
            ConversationModelProvider modelProvider) {
        this.owner = owner;
        this.project = project;
        this.title = title;
        this.mode = mode;
        this.modelProvider = modelProvider;
        this.createdAt = Instant.now();
        this.updatedAt = this.createdAt;
    }

    public void rename(String title) {
        this.title = title;
        touch();
    }

    public void bindProject(Project project) {
        this.project = project;
        this.mode = ConversationMode.PROJECT;
        touch();
    }

    public void selectModel(ConversationModelProvider modelProvider) {
        this.modelProvider = modelProvider;
        touch();
    }

    public void touch() {
        this.updatedAt = Instant.now();
    }

    public UUID getId() {
        return id;
    }

    public UserAccount getOwner() {
        return owner;
    }

    public Project getProject() {
        return project;
    }

    public String getTitle() {
        return title;
    }

    public ConversationMode getMode() {
        return mode;
    }

    public ConversationModelProvider getModelProvider() {
        return modelProvider;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    public Instant getUpdatedAt() {
        return updatedAt;
    }
}
