package com.aioagent.business.auth;

import com.aioagent.business.common.ApiException;
import com.aioagent.business.config.AppProperties;
import java.util.Locale;
import org.springframework.http.HttpStatus;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class AuthService {

    private final UserRepository users;
    private final PasswordEncoder passwordEncoder;
    private final JwtService jwtService;
    private final AppProperties properties;

    public AuthService(
            UserRepository users,
            PasswordEncoder passwordEncoder,
            JwtService jwtService,
            AppProperties properties) {
        this.users = users;
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

    @Transactional(readOnly = true)
    public AuthResult login(String rawUsername, String password) {
        String username = normalizeUsername(rawUsername);
        UserAccount user = users.findByUsernameIgnoreCase(username)
                .orElseThrow(() -> new ApiException(HttpStatus.UNAUTHORIZED, "INVALID_CREDENTIALS", "用户名或密码错误"));
        if (!passwordEncoder.matches(password, user.getPasswordHash())) {
            throw new ApiException(HttpStatus.UNAUTHORIZED, "INVALID_CREDENTIALS", "用户名或密码错误");
        }
        return result(user);
    }

    private AuthResult result(UserAccount user) {
        JwtService.Token token = jwtService.issue(user);
        return new AuthResult(user, token);
    }

    private String normalizeUsername(String username) {
        return username.trim().toLowerCase(Locale.ROOT);
    }

    public record AuthResult(UserAccount user, JwtService.Token token) {
    }
}
