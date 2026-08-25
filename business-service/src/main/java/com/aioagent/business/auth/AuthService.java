package com.aioagent.business.auth;

import com.aioagent.business.common.ApiException;
import com.aioagent.business.config.AppProperties;
import java.time.Instant;
import java.util.Locale;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class AuthService {

    private final UserRepository users;
    private final RefreshTokenRepository refreshTokens;
    private final PasswordResetTokenRepository resetTokens;
    private final PasswordEncoder passwordEncoder;
    private final JwtService jwtService;
    private final AppProperties properties;

    public AuthService(
            UserRepository users,
            RefreshTokenRepository refreshTokens,
            PasswordResetTokenRepository resetTokens,
            PasswordEncoder passwordEncoder,
            JwtService jwtService,
            AppProperties properties) {
        this.users = users;
        this.refreshTokens = refreshTokens;
        this.resetTokens = resetTokens;
        this.passwordEncoder = passwordEncoder;
        this.jwtService = jwtService;
        this.properties = properties;
    }

    @Transactional
    public AuthResult register(String rawUsername, String password) {
        if (!properties.getSecurity().isPublicRegistrationEnabled()) {
            throw new ApiException(HttpStatus.FORBIDDEN, "REGISTRATION_DISABLED", "公开注册已关闭");
        }
        String username = normalizeUsername(rawUsername);
        if (users.existsByUsernameIgnoreCase(username)) {
            throw new ApiException(HttpStatus.CONFLICT, "USERNAME_EXISTS", "用户名已存在");
        }
        UserAccount user = users.save(new UserAccount(username, passwordEncoder.encode(password), UserRole.USER));
        return result(user);
    }

    @Transactional
    public AuthResult login(String rawUsername, String password) {
        String username = normalizeUsername(rawUsername);
        UserAccount user = users.findLockedByUsernameIgnoreCase(username)
                .orElseThrow(() -> invalidCredentials());
        if (!passwordEncoder.matches(password, user.getPasswordHash())) {
            throw invalidCredentials();
        }
        return result(user);
    }

    @Transactional
    public AuthResult refresh(String rawToken) {
        String tokenHash = TokenHashing.sha256(requiredToken(rawToken));
        UUID userId = refreshTokens.findUserIdByTokenHash(tokenHash)
                .orElseThrow(() -> invalidRefreshToken());
        UserAccount user = users.findLockedById(userId)
                .orElseThrow(() -> invalidRefreshToken());
        RefreshToken current = refreshTokens.findLockedByTokenHash(tokenHash)
                .orElseThrow(() -> invalidRefreshToken());
        if (!current.isActive(Instant.now())) {
            throw invalidRefreshToken();
        }
        current.revoke();
        return result(user);
    }

    @Transactional
    public void logout(String rawRefreshToken) {
        if (rawRefreshToken == null || rawRefreshToken.isBlank()) {
            return;
        }
        refreshTokens.findLockedByTokenHash(TokenHashing.sha256(rawRefreshToken)).ifPresent(RefreshToken::revoke);
    }

    @Transactional
    public void changePassword(UUID userId, String currentPassword, String newPassword) {
        UserAccount user = users.findLockedById(userId)
                .orElseThrow(() -> new ApiException(HttpStatus.UNAUTHORIZED, "USER_NOT_FOUND", "当前用户不存在"));
        if (!passwordEncoder.matches(currentPassword, user.getPasswordHash())) {
            throw invalidCredentials();
        }
        user.changePasswordHash(passwordEncoder.encode(newPassword));
        revokeAllRefreshTokens(user);
    }

    @Transactional
    public ResetToken issuePasswordReset(String rawUsername) {
        UserAccount user = users.findByUsernameIgnoreCase(normalizeUsername(rawUsername))
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "USER_NOT_FOUND", "用户不存在"));
        String value = TokenHashing.randomToken();
        Instant expiresAt = Instant.now().plus(properties.getSecurity().getPasswordResetTtl());
        resetTokens.save(new PasswordResetToken(user, TokenHashing.sha256(value), expiresAt));
        return new ResetToken(value, expiresAt);
    }

    @Transactional
    public void resetPassword(String rawToken, String newPassword) {
        String tokenHash = TokenHashing.sha256(requiredResetToken(rawToken));
        UUID userId = resetTokens.findUserIdByTokenHash(tokenHash)
                .orElseThrow(() -> invalidResetToken());
        UserAccount user = users.findLockedById(userId)
                .orElseThrow(() -> invalidResetToken());
        PasswordResetToken token = resetTokens.findLockedByTokenHash(tokenHash)
                .orElseThrow(() -> invalidResetToken());
        if (!token.isActive(Instant.now())) {
            throw invalidResetToken();
        }
        token.use();
        user.changePasswordHash(passwordEncoder.encode(newPassword));
        revokeAllRefreshTokens(user);
    }

    private AuthResult result(UserAccount user) {
        JwtService.Token accessToken = jwtService.issue(user);
        String refreshValue = TokenHashing.randomToken();
        Instant refreshExpiresAt = Instant.now().plus(properties.getSecurity().getRefreshTokenTtl());
        refreshTokens.save(new RefreshToken(user, TokenHashing.sha256(refreshValue), refreshExpiresAt));
        return new AuthResult(user, accessToken, refreshValue, refreshExpiresAt);
    }

    private void revokeAllRefreshTokens(UserAccount user) {
        refreshTokens.revokeAllActiveByUserId(user.getId(), Instant.now());
    }

    private ApiException invalidCredentials() {
        return new ApiException(HttpStatus.UNAUTHORIZED, "INVALID_CREDENTIALS", "用户名或密码错误");
    }

    private ApiException invalidRefreshToken() {
        return new ApiException(HttpStatus.UNAUTHORIZED, "INVALID_REFRESH_TOKEN", "登录会话无效或已过期");
    }

    private ApiException invalidResetToken() {
        return new ApiException(HttpStatus.BAD_REQUEST, "INVALID_RESET_TOKEN", "密码重置凭证无效或已过期");
    }

    private String requiredToken(String token) {
        if (token == null || token.isBlank()) {
            throw invalidRefreshToken();
        }
        return token;
    }

    private String requiredResetToken(String token) {
        if (token == null || token.isBlank()) {
            throw invalidResetToken();
        }
        return token;
    }

    private String normalizeUsername(String username) {
        return username.trim().toLowerCase(Locale.ROOT);
    }

    public record AuthResult(
            UserAccount user,
            JwtService.Token token,
            String refreshToken,
            Instant refreshExpiresAt) {
    }

    public record ResetToken(String value, Instant expiresAt) {
    }
}
