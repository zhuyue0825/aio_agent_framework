package com.aioagent.business.auth;

import com.aioagent.business.config.AppProperties;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.core.annotation.Order;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

@Component
@Order(0)
public class BootstrapAdmin implements ApplicationRunner {

    private static final Logger log = LoggerFactory.getLogger(BootstrapAdmin.class);
    private final UserRepository users;
    private final RefreshTokenRepository refreshTokens;
    private final PasswordEncoder passwordEncoder;
    private final AppProperties properties;

    public BootstrapAdmin(
            UserRepository users,
            RefreshTokenRepository refreshTokens,
            PasswordEncoder passwordEncoder,
            AppProperties properties) {
        this.users = users;
        this.refreshTokens = refreshTokens;
        this.passwordEncoder = passwordEncoder;
        this.properties = properties;
    }

    @Override
    @Transactional
    public void run(ApplicationArguments args) {
        String username = properties.getBootstrap().getAdminUsername().trim().toLowerCase();
        String password = properties.getBootstrap().getAdminPassword();
        if (username.isBlank()) {
            throw new IllegalStateException("AIO_BOOTSTRAP_ADMIN_USERNAME must not be blank");
        }
        if (password == null || password.length() < 12) {
            throw new IllegalStateException("AIO_BOOTSTRAP_ADMIN_PASSWORD must contain at least 12 characters");
        }

        UserAccount existing = users.findByUsernameIgnoreCase(username).orElse(null);
        if (existing != null) {
            if (existing.getRole() != UserRole.ADMIN) {
                throw new IllegalStateException("Bootstrap administrator username belongs to a non-admin user");
            }
            if (!passwordEncoder.matches(password, existing.getPasswordHash())) {
                existing.changePasswordHash(passwordEncoder.encode(password));
                refreshTokens.findAllByUserId(existing.getId()).forEach(RefreshToken::revoke);
                users.save(existing);
                log.info("Rotated bootstrap admin password for '{}'", username);
            }
            return;
        }
        UserAccount admin = new UserAccount(
                username,
                passwordEncoder.encode(password),
                UserRole.ADMIN);
        users.save(admin);
        log.info("Created bootstrap admin '{}'", username);
    }
}
