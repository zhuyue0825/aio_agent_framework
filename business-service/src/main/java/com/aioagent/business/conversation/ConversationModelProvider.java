package com.aioagent.business.conversation;

import java.util.Locale;

public enum ConversationModelProvider {
    LOCAL,
    REMOTE;

    public static ConversationModelProvider parse(String value) {
        if (value == null || value.isBlank() || "local".equalsIgnoreCase(value)) {
            return LOCAL;
        }
        if ("remote".equalsIgnoreCase(value)) {
            return REMOTE;
        }
        throw new IllegalArgumentException("Unsupported model provider: " + value);
    }

    public String apiValue() {
        return name().toLowerCase(Locale.ROOT);
    }

    public String defaultModelId() {
        return this == REMOTE ? "remote:deepseek" : "local:minimind-64m";
    }
}
