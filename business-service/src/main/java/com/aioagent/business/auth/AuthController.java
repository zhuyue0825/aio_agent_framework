package com.aioagent.business.auth;

import com.aioagent.business.config.AppProperties;
import com.aioagent.business.security.RateLimitService;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;
import java.time.Duration;
import java.time.Instant;
import java.util.Map;
import java.util.UUID;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseCookie;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.Authentication;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.web.bind.annotation.CookieValue;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/auth")
public class AuthController {

    static final String REFRESH_COOKIE = "aio_refresh_token";
    private final AuthService authService;
    private final CurrentUser currentUser;
    private final AppProperties properties;
    private final RateLimitService rateLimits;
    private final TokenRevocationService revocations;

    public AuthController(
            AuthService authService,
            CurrentUser currentUser,
            AppProperties properties,
            RateLimitService rateLimits,
            TokenRevocationService revocations) {
        this.authService = authService;
        this.currentUser = currentUser;
        this.properties = properties;
        this.rateLimits = rateLimits;
        this.revocations = revocations;
    }

    @GetMapping("/config")
    public Map<String, Boolean> config() {
        return Map.of("registration_enabled", properties.getSecurity().isPublicRegistrationEnabled());
    }

    @PostMapping("/register")
    public Map<String, Object> register(
            @Valid @RequestBody Credentials request,
            HttpServletRequest servletRequest,
            HttpServletResponse response) {
        limit("register", servletRequest, request.username());
        return response(authService.register(request.username(), request.password()), response);
    }

    @PostMapping("/login")
    public Map<String, Object> login(
            @Valid @RequestBody Credentials request,
            HttpServletRequest servletRequest,
            HttpServletResponse response) {
        limit("login", servletRequest, request.username());
        return response(authService.login(request.username(), request.password()), response);
    }

    @PostMapping("/refresh")
    public Map<String, Object> refresh(
            @CookieValue(name = REFRESH_COOKIE, required = false) String refreshToken,
            HttpServletRequest servletRequest,
            HttpServletResponse response) {
        limit("refresh", servletRequest, "session");
        return response(authService.refresh(refreshToken), response);
    }

    @PostMapping("/logout")
    public Map<String, Boolean> logout(
            @CookieValue(name = REFRESH_COOKIE, required = false) String refreshToken,
            Authentication authentication,
            HttpServletResponse response) {
        authService.logout(refreshToken);
        if (authentication != null && authentication.getPrincipal() instanceof Jwt jwt) {
            revocations.revoke(jwt.getId(), jwt.getExpiresAt());
        }
        clearRefreshCookie(response);
        return Map.of("ok", true);
    }

    @PostMapping("/password")
    public Map<String, Boolean> changePassword(
            @Valid @RequestBody ChangePasswordRequest request,
            Authentication authentication) {
        authService.changePassword(
                currentUser.require(authentication),
                request.currentPassword(),
                request.newPassword());
        return Map.of("ok", true);
    }

    @PostMapping("/password-reset-token")
    @PreAuthorize("hasRole('ADMIN')")
    public Map<String, Object> issuePasswordReset(@Valid @RequestBody ResetTokenRequest request) {
        AuthService.ResetToken token = authService.issuePasswordReset(request.username());
        return Map.of("reset_token", token.value(), "expires_at", token.expiresAt());
    }

    @PostMapping("/reset-password")
    public Map<String, Boolean> resetPassword(@Valid @RequestBody ResetPasswordRequest request) {
        authService.resetPassword(request.resetToken(), request.newPassword());
        return Map.of("ok", true);
    }

    @GetMapping("/me")
    public Map<String, UserResponse> me(Authentication authentication) {
        return Map.of("user", UserResponse.from(currentUser.require(authentication)));
    }

    private Map<String, Object> response(AuthService.AuthResult result, HttpServletResponse response) {
        response.addHeader(HttpHeaders.SET_COOKIE, refreshCookie(result.refreshToken(), result.refreshExpiresAt()).toString());
        return Map.of(
                "access_token", result.token().value(),
                "token_type", "Bearer",
                "expires_at", result.token().expiresAt(),
                "user", UserResponse.from(result.user()));
    }

    private ResponseCookie refreshCookie(String value, Instant expiresAt) {
        return ResponseCookie.from(REFRESH_COOKIE, value)
                .httpOnly(true)
                .secure(properties.getSecurity().isRefreshCookieSecure())
                .sameSite("Strict")
                .path("/api/v1/auth")
                .maxAge(Duration.between(Instant.now(), expiresAt))
                .build();
    }

    private void clearRefreshCookie(HttpServletResponse response) {
        ResponseCookie cookie = ResponseCookie.from(REFRESH_COOKIE, "")
                .httpOnly(true)
                .secure(properties.getSecurity().isRefreshCookieSecure())
                .sameSite("Strict")
                .path("/api/v1/auth")
                .maxAge(Duration.ZERO)
                .build();
        response.addHeader(HttpHeaders.SET_COOKIE, cookie.toString());
    }

    private void limit(String action, HttpServletRequest request, String subject) {
        String address = request.getRemoteAddr() == null ? "unknown" : request.getRemoteAddr();
        String normalized = subject == null ? "unknown" : subject.strip().toLowerCase();
        rateLimits.require(
                "auth:" + action + ":" + address + ":" + normalized,
                properties.getSecurity().getLoginAttemptsPerMinute(),
                Duration.ofMinutes(1));
    }

    public record Credentials(
            @NotBlank
            @Size(min = 3, max = 50)
            @Pattern(regexp = "[A-Za-z0-9_.-]+", message = "只能包含字母、数字、点、下划线和横线")
            String username,
            @NotBlank @Size(min = 8, max = 72) String password) {
    }

    public record ChangePasswordRequest(
            @NotBlank @Size(min = 8, max = 72) String currentPassword,
            @NotBlank @Size(min = 8, max = 72) String newPassword) {
    }

    public record ResetTokenRequest(@NotBlank @Size(max = 50) String username) {
    }

    public record ResetPasswordRequest(
            @NotBlank @Size(max = 200) String resetToken,
            @NotBlank @Size(min = 8, max = 72) String newPassword) {
    }

    public record UserResponse(UUID id, String username, UserRole role, Instant createdAt) {
        public static UserResponse from(UserAccount user) {
            return new UserResponse(user.getId(), user.getUsername(), user.getRole(), user.getCreatedAt());
        }
    }
}
