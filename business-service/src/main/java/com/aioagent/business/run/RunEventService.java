package com.aioagent.business.run;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import tools.jackson.core.JacksonException;
import tools.jackson.databind.ObjectMapper;

@Service
public class RunEventService {

    private static final Logger log = LoggerFactory.getLogger(RunEventService.class);
    private final RunEventRepository events;
    private final RunEventBroadcaster broadcaster;
    private final ObjectMapper mapper;

    public RunEventService(RunEventRepository events, RunEventBroadcaster broadcaster, ObjectMapper mapper) {
        this.events = events;
        this.broadcaster = broadcaster;
        this.mapper = mapper;
    }

    public RunEvent append(AgentRun run, String eventType, Object payload) {
        String json;
        try {
            json = mapper.writeValueAsString(payload == null ? java.util.Map.of() : payload);
        } catch (JacksonException exception) {
            json = "{}";
        }
        RunEvent event = events.saveAndFlush(new RunEvent(run, eventType, json));
        if (TransactionSynchronizationManager.isActualTransactionActive()
                && TransactionSynchronizationManager.isSynchronizationActive()) {
            TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
                @Override
                public void afterCommit() {
                    broadcast(event);
                }
            });
        } else {
            broadcast(event);
        }
        return event;
    }

    private void broadcast(RunEvent event) {
        try {
            broadcaster.broadcast(event);
        } catch (RuntimeException exception) {
            log.atWarn()
                    .addKeyValue("run_id", event.getRun().getId())
                    .addKeyValue("event_id", event.getId())
                    .log("run_event_broadcast_failed", exception);
        }
    }
}
