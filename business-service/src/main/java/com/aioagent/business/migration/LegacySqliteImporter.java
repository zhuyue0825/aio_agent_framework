package com.aioagent.business.migration;

import com.aioagent.business.auth.UserAccount;
import com.aioagent.business.auth.UserRepository;
import com.aioagent.business.config.AppProperties;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.UUID;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.core.annotation.Order;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

@Component
@Order(10)
public class LegacySqliteImporter implements ApplicationRunner {

    private static final Logger log = LoggerFactory.getLogger(LegacySqliteImporter.class);
    private final AppProperties properties;
    private final UserRepository users;
    private final JdbcTemplate postgres;

    public LegacySqliteImporter(AppProperties properties, UserRepository users, JdbcTemplate postgres) {
        this.properties = properties;
        this.users = users;
        this.postgres = postgres;
    }

    @Override
    @Transactional
    public void run(ApplicationArguments args) throws Exception {
        if (!properties.getLegacyImport().isEnabled()) {
            return;
        }
        Path sqlitePath = Path.of(properties.getLegacyImport().getSqlitePath()).toAbsolutePath().normalize();
        if (!Files.isRegularFile(sqlitePath)) {
            log.warn("Legacy SQLite import enabled, but {} does not exist", sqlitePath);
            return;
        }
        String importKey = "sqlite:" + sqlitePath;
        Boolean imported = postgres.queryForObject(
                "select exists(select 1 from legacy_imports where import_key = ?)",
                Boolean.class,
                importKey);
        if (Boolean.TRUE.equals(imported)) {
            return;
        }
        UserAccount owner = users.findByUsernameIgnoreCase(properties.getLegacyImport().getOwnerUsername())
                .orElseThrow(() -> new IllegalStateException("Legacy import owner does not exist"));

        int conversationCount;
        int messageCount;
        try (Connection sqlite = DriverManager.getConnection("jdbc:sqlite:" + sqlitePath)) {
            conversationCount = importConversations(sqlite, owner.getId());
            messageCount = importMessages(sqlite);
        }
        postgres.update(
                "insert into legacy_imports(import_key, completed_at, conversations_imported, messages_imported) values (?, ?, ?, ?)",
                importKey,
                Timestamp.from(Instant.now()),
                conversationCount,
                messageCount);
        log.info("Imported {} conversations and {} messages from legacy SQLite", conversationCount, messageCount);
    }

    private int importConversations(Connection sqlite, UUID ownerId) throws SQLException {
        int imported = 0;
        String query = "select id, title, created_at, updated_at from conversations order by created_at";
        try (PreparedStatement statement = sqlite.prepareStatement(query); ResultSet rows = statement.executeQuery()) {
            while (rows.next()) {
                imported += postgres.update(
                        """
                        insert into conversations(id, owner_id, project_id, title, mode, created_at, updated_at)
                        values (?, ?, null, ?, 'CHAT', ?, ?)
                        on conflict (id) do nothing
                        """,
                        UUID.fromString(rows.getString("id")),
                        ownerId,
                        rows.getString("title"),
                        timestamp(rows.getDouble("created_at")),
                        timestamp(rows.getDouble("updated_at")));
            }
        }
        return imported;
    }

    private int importMessages(Connection sqlite) throws SQLException {
        int imported = 0;
        String query = "select id, conversation_id, role, content, metadata_json, created_at from messages order by created_at";
        try (PreparedStatement statement = sqlite.prepareStatement(query); ResultSet rows = statement.executeQuery()) {
            while (rows.next()) {
                String role = rows.getString("role").toUpperCase();
                if (!role.equals("USER") && !role.equals("ASSISTANT") && !role.equals("ERROR")) {
                    role = "ERROR";
                }
                imported += postgres.update(
                        """
                        insert into messages(id, conversation_id, role, content, metadata_json, created_at)
                        values (?, ?, ?, ?, ?, ?)
                        on conflict (id) do nothing
                        """,
                        UUID.fromString(rows.getString("id")),
                        UUID.fromString(rows.getString("conversation_id")),
                        role,
                        rows.getString("content"),
                        rows.getString("metadata_json"),
                        timestamp(rows.getDouble("created_at")));
            }
        }
        return imported;
    }

    private Timestamp timestamp(double epochSeconds) {
        return Timestamp.from(Instant.ofEpochMilli((long) (epochSeconds * 1000)));
    }
}
