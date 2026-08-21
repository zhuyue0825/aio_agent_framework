package com.aioagent.business.agent;

public class AgentServiceException extends RuntimeException {

    private final boolean timeout;
    private final String errorCode;

    public AgentServiceException(String message, Throwable cause, boolean timeout, String errorCode) {
        super(message, cause);
        this.timeout = timeout;
        this.errorCode = errorCode;
    }

    public boolean isTimeout() {
        return timeout;
    }

    public String getErrorCode() {
        return errorCode;
    }
}
