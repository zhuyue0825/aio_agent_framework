package com.aioagent.business.auth;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;
import java.time.Instant;
import java.util.Map;
import java.util.UUID;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/auth")
public class AuthController {

    private final AuthService authService;
    private final CurrentUser currentUser;

    public AuthController(AuthService authService, CurrentUser currentUser) {
        this.authService = authService;
        this.currentUser = currentUser;
    }

    @PostMapping("/register")
    public Map<String, Object> register(@Valid @RequestBody Credentials request) {
        return response(authService.register(request.username(), request.password()));
    }

    @PostMapping("/login")
    public Map<String, Object> login(@Valid @RequestBody Credentials request) {
        return response(authService.login(request.username(), request.password()));
    }

    @GetMapping("/me")
    public Map<String, UserResponse> me(Authentication authentication) {
        return Map.of("user", UserResponse.from(currentUser.require(authentication)));
    }

    private Map<String, Object> response(AuthService.AuthResult result) {
        return Map.of(
                "access_token", result.token().value(),
                "token_type", "Bearer",
                "expires_at", result.token().expiresAt(),
                "user", UserResponse.from(result.user()));
    }

    public record Credentials(
            @NotBlank
            @Size(min = 3, max = 50)
            @Pattern(regexp = "[A-Za-z0-9_.-]+", message = "只能包含字母、数字、点、下划线和横线")
            String username,
            @NotBlank @Size(min = 8, max = 72) String password) {
    }

    public record UserResponse(UUID id, String username, UserRole role, Instant createdAt) {
        public static UserResponse from(UserAccount user) {
            return new UserResponse(user.getId(), user.getUsername(), user.getRole(), user.getCreatedAt());
        }
    }
}
