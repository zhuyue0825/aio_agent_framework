package com.aioagent.business.run;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

@Component
@ConditionalOnProperty(prefix = "app.redis", name = "enabled", havingValue = "false", matchIfMissing = true)
public class LocalRunEventBroadcaster implements RunEventBroadcaster {

    private final SseRunEventHub hub;

    public LocalRunEventBroadcaster(SseRunEventHub hub) {
        this.hub = hub;
    }

    @Override
    public void broadcast(RunEvent event) {
        hub.publish(event);
    }
}
