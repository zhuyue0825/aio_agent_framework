package com.aioagent.business.run;

import org.springframework.stereotype.Service;
import tools.jackson.core.JacksonException;
import tools.jackson.databind.ObjectMapper;

@Service
public class RunEventService {

    private final RunEventRepository events;
    private final SseRunEventHub hub;
    private final ObjectMapper mapper;

    public RunEventService(RunEventRepository events, SseRunEventHub hub, ObjectMapper mapper) {
        this.events = events;
        this.hub = hub;
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
        hub.publish(event);
        return event;
    }
}
