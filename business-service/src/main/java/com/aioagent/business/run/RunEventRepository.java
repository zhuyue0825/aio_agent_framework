package com.aioagent.business.run;

import java.util.List;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import java.util.Optional;

public interface RunEventRepository extends JpaRepository<RunEvent, Long> {
    List<RunEvent> findAllByRunIdOrderByIdAsc(UUID runId);

    List<RunEvent> findAllByRunIdAndIdGreaterThanOrderByIdAsc(UUID runId, long afterId, Pageable pageable);

    @Query("select event from RunEvent event join fetch event.run where event.id = :id")
    Optional<RunEvent> findByIdWithRun(@Param("id") long id);
}
