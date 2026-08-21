package com.aioagent.business.run;

import java.util.UUID;

public interface AgentRunDispatcher {
    void dispatch(UUID runId);
}
