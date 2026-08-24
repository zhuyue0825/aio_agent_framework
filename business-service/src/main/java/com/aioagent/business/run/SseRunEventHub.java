package com.aioagent.business.run;

import java.io.IOException;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.Set;
import org.springframework.stereotype.Component;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;
import org.springframework.data.domain.PageRequest;
import tools.jackson.databind.ObjectMapper;

@Component
public class SseRunEventHub {

    private static final long EMITTER_TIMEOUT_MILLIS = 30L * 60L * 1000L;
    private final RunEventRepository events;
    private final ObjectMapper mapper;
    private final ConcurrentHashMap<UUID, CopyOnWriteArrayList<Subscriber>> emitters = new ConcurrentHashMap<>();

    public SseRunEventHub(RunEventRepository events, ObjectMapper mapper) {
        this.events = events;
        this.mapper = mapper;
    }

    public SseEmitter subscribe(AgentRun run) {
        return subscribe(run, 0L);
    }

    public SseEmitter subscribe(AgentRun run, long afterEventId) {
        UUID runId = run.getId();
        SseEmitter emitter = new SseEmitter(EMITTER_TIMEOUT_MILLIS);
        Subscriber subscriber = new Subscriber(emitter);
        emitters.computeIfAbsent(runId, ignored -> new CopyOnWriteArrayList<>()).add(subscriber);
        emitter.onCompletion(() -> remove(runId, subscriber));
        emitter.onTimeout(() -> remove(runId, subscriber));
        emitter.onError(error -> remove(runId, subscriber));

        List<RunEvent> history = events.findAllByRunIdAndIdGreaterThanOrderByIdAsc(
                runId,
                Math.max(0L, afterEventId),
                PageRequest.of(0, 500));
        try {
            for (RunEvent event : history) {
                send(subscriber, event);
            }
            if (run.getStatus().isTerminal()) {
                emitter.complete();
            }
        } catch (IOException exception) {
            remove(runId, subscriber);
            emitter.completeWithError(exception);
        }
        return emitter;
    }

    public void publish(RunEvent event) {
        UUID runId = event.getRun().getId();
        List<Subscriber> current = emitters.getOrDefault(runId, new CopyOnWriteArrayList<>());
        for (Subscriber subscriber : current) {
            try {
                send(subscriber, event);
                if (isTerminal(event.getEventType())) {
                    subscriber.emitter().complete();
                }
            } catch (IOException exception) {
                remove(runId, subscriber);
                subscriber.emitter().completeWithError(exception);
            }
        }
        if (isTerminal(event.getEventType())) {
            emitters.remove(runId);
        }
    }

    private void send(Subscriber subscriber, RunEvent event) throws IOException {
        synchronized (subscriber) {
            if (!subscriber.deliveredEventIds().add(event.getId())) {
                return;
            }
            subscriber.emitter().send(SseEmitter.event()
                    .id(String.valueOf(event.getId()))
                    .name(event.getEventType())
                    .data(RunDtos.RunEventResponse.from(event, mapper)));
        }
    }

    private boolean isTerminal(String type) {
        return type.equals("run.succeeded")
                || type.equals("run.failed")
                || type.equals("run.cancelled")
                || type.equals("run.timed_out");
    }

    private void remove(UUID runId, Subscriber subscriber) {
        CopyOnWriteArrayList<Subscriber> current = emitters.get(runId);
        if (current == null) {
            return;
        }
        current.remove(subscriber);
        if (current.isEmpty()) {
            emitters.remove(runId, current);
        }
    }

    private record Subscriber(SseEmitter emitter, Set<Long> deliveredEventIds) {
        private Subscriber(SseEmitter emitter) {
            this(emitter, ConcurrentHashMap.newKeySet());
        }
    }
}
