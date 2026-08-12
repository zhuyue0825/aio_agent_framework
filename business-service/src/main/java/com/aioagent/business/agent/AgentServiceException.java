package com.aioagent.business.agent;

public class AgentServiceException extends RuntimeException {

    private final boolean timeout;

    public AgentServiceException(String message, Throwable cause, boolean timeout) {
        super(message, cause);
        this.timeout = timeout;
    }

    public boolean isTimeout() {
        return timeout;
    }
}
