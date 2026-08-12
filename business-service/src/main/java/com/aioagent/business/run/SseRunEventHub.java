package com.aioagent.business.run;

import java.io.IOException;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CopyOnWriteArrayList;
import org.springframework.stereotype.Component;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;
import tools.jackson.databind.ObjectMapper;

@Component
public class SseRunEventHub {

    private static final long EMITTER_TIMEOUT_MILLIS = 30L * 60L * 1000L;
    private final RunEventRepository events;
    private final ObjectMapper mapper;
    private final ConcurrentHashMap<UUID, CopyOnWriteArrayList<SseEmitter>> emitters = new ConcurrentHashMap<>();

    public SseRunEventHub(RunEventRepository events, ObjectMapper mapper) {
        this.events = events;
        this.mapper = mapper;
    }

    public SseEmitter subscribe(AgentRun run) {
        UUID runId = run.getId();
        SseEmitter emitter = new SseEmitter(EMITTER_TIMEOUT_MILLIS);
        emitters.computeIfAbsent(runId, ignored -> new CopyOnWriteArrayList<>()).add(emitter);
        emitter.onCompletion(() -> remove(runId, emitter));
        emitter.onTimeout(() -> remove(runId, emitter));
        emitter.onError(error -> remove(runId, emitter));

        List<RunEvent> history = events.findAllByRunIdOrderByIdAsc(runId);
        try {
            for (RunEvent event : history) {
                send(emitter, event);
            }
            if (run.getStatus().isTerminal()) {
                emitter.complete();
            }
        } catch (IOException exception) {
            remove(runId, emitter);
            emitter.completeWithError(exception);
        }
        return emitter;
    }

    public void publish(RunEvent event) {
        UUID runId = event.getRun().getId();
        List<SseEmitter> current = emitters.getOrDefault(runId, new CopyOnWriteArrayList<>());
        for (SseEmitter emitter : current) {
            try {
                send(emitter, event);
                if (isTerminal(event.getEventType())) {
                    emitter.complete();
                }
            } catch (IOException exception) {
                remove(runId, emitter);
                emitter.completeWithError(exception);
            }
        }
        if (isTerminal(event.getEventType())) {
            emitters.remove(runId);
        }
    }

    private void send(SseEmitter emitter, RunEvent event) throws IOException {
        emitter.send(SseEmitter.event()
                .id(String.valueOf(event.getId()))
                .name(event.getEventType())
                .data(RunDtos.RunEventResponse.from(event, mapper)));
    }

    private boolean isTerminal(String type) {
        return type.equals("run.succeeded")
                || type.equals("run.failed")
                || type.equals("run.cancelled")
                || type.equals("run.timed_out");
    }

    private void remove(UUID runId, SseEmitter emitter) {
        CopyOnWriteArrayList<SseEmitter> current = emitters.get(runId);
        if (current == null) {
            return;
        }
        current.remove(emitter);
        if (current.isEmpty()) {
            emitters.remove(runId, current);
        }
    }
}
