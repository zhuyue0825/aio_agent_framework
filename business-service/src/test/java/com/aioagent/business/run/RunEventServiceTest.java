package com.aioagent.business.run;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import org.junit.jupiter.api.Test;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import tools.jackson.databind.ObjectMapper;

class RunEventServiceTest {

    @Test
    void broadcastsOnlyAfterTheSurroundingTransactionCommits() {
        RunEventRepository events = mock(RunEventRepository.class);
        RunEventBroadcaster broadcaster = mock(RunEventBroadcaster.class);
        AgentRun run = mock(AgentRun.class);
        when(events.saveAndFlush(any(RunEvent.class))).thenAnswer(invocation -> invocation.getArgument(0));
        RunEventService service = new RunEventService(events, broadcaster, new ObjectMapper());

        TransactionSynchronizationManager.setActualTransactionActive(true);
        TransactionSynchronizationManager.initSynchronization();
        try {
            RunEvent event = service.append(run, "run.started", java.util.Map.of("status", "RUNNING"));

            verifyNoInteractions(broadcaster);
            TransactionSynchronizationManager.getSynchronizations()
                    .forEach(TransactionSynchronization::afterCommit);
            verify(broadcaster).broadcast(event);
        } finally {
            TransactionSynchronizationManager.clearSynchronization();
            TransactionSynchronizationManager.setActualTransactionActive(false);
        }
    }
}
