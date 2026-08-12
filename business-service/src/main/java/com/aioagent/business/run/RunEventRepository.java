package com.aioagent.business.run;

import java.util.List;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;

public interface RunEventRepository extends JpaRepository<RunEvent, Long> {
    List<RunEvent> findAllByRunIdOrderByIdAsc(UUID runId);
}
