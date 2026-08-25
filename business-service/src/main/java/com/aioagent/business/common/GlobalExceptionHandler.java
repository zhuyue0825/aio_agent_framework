package com.aioagent.business.common;

import com.aioagent.business.agent.AgentServiceException;
import jakarta.validation.ConstraintViolationException;
import java.util.List;
import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.slf4j.MDC;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.dao.OptimisticLockingFailureException;
import org.springframework.dao.PessimisticLockingFailureException;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice
public class GlobalExceptionHandler {

    private static final Logger log = LoggerFactory.getLogger(GlobalExceptionHandler.class);

    @ExceptionHandler(ApiException.class)
    ResponseEntity<Map<String, Object>> handleApiException(ApiException exception) {
        return response(exception.getStatus(), exception.getCode(), exception.getMessage(), List.of());
    }

    @ExceptionHandler(MethodArgumentNotValidException.class)
    ResponseEntity<Map<String, Object>> handleValidation(MethodArgumentNotValidException exception) {
        List<String> details = exception.getBindingResult().getFieldErrors().stream()
                .map(error -> error.getField() + ": " + error.getDefaultMessage())
                .toList();
        return response(HttpStatus.BAD_REQUEST, "VALIDATION_ERROR", "请求参数不合法", details);
    }

    @ExceptionHandler(ConstraintViolationException.class)
    ResponseEntity<Map<String, Object>> handleConstraintViolation(ConstraintViolationException exception) {
        List<String> details = exception.getConstraintViolations().stream()
                .map(violation -> violation.getPropertyPath() + ": " + violation.getMessage())
                .toList();
        return response(HttpStatus.BAD_REQUEST, "VALIDATION_ERROR", "请求参数不合法", details);
    }

    @ExceptionHandler(DataIntegrityViolationException.class)
    ResponseEntity<Map<String, Object>> handleConflict(DataIntegrityViolationException exception) {
        return response(HttpStatus.CONFLICT, "CONFLICT", "资源状态冲突，请刷新后重试", List.of());
    }

    @ExceptionHandler(OptimisticLockingFailureException.class)
    ResponseEntity<Map<String, Object>> handleOptimisticConflict(OptimisticLockingFailureException exception) {
        return response(HttpStatus.CONFLICT, "CONCURRENT_MODIFICATION", "资源已被其他请求更新，请刷新后重试", List.of());
    }

    @ExceptionHandler(PessimisticLockingFailureException.class)
    ResponseEntity<Map<String, Object>> handleLockConflict(RuntimeException exception) {
        return response(HttpStatus.CONFLICT, "RESOURCE_BUSY", "资源正在被处理，请稍后重试", List.of());
    }

    @ExceptionHandler(AccessDeniedException.class)
    ResponseEntity<Map<String, Object>> handleAccessDenied(AccessDeniedException exception) {
        return response(HttpStatus.FORBIDDEN, "FORBIDDEN", "无访问权限", List.of());
    }

    @ExceptionHandler(AgentServiceException.class)
    ResponseEntity<Map<String, Object>> handleAgentService(AgentServiceException exception) {
        log.atWarn()
                .addKeyValue("error_type", exception.getCause() == null
                        ? exception.getClass().getSimpleName()
                        : exception.getCause().getClass().getSimpleName())
                .log("internal_agent_service_request_failed");
        return response(HttpStatus.BAD_GATEWAY, "AGENT_SERVICE_UNAVAILABLE", "Agent 服务暂时不可用，请稍后重试", List.of());
    }

    @ExceptionHandler(Exception.class)
    ResponseEntity<Map<String, Object>> handleUnexpected(Exception exception) {
        log.error("Unhandled request error", exception);
        return response(HttpStatus.INTERNAL_SERVER_ERROR, "INTERNAL_ERROR", "服务内部错误", List.of());
    }

    private ResponseEntity<Map<String, Object>> response(
            HttpStatus status,
            String code,
            String message,
            List<String> details) {
        Map<String, Object> error = Map.of(
                "code", code,
                "message", message,
                "trace_id", MDC.get("trace_id") == null ? "" : MDC.get("trace_id"),
                "details", details);
        return ResponseEntity.status(status).body(Map.of("error", error));
    }
}
