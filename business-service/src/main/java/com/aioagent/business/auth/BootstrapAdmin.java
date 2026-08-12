package com.aioagent.business.auth;

import com.aioagent.business.config.AppProperties;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.core.annotation.Order;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Component;

@Component
@Order(0)
public class BootstrapAdmin implements ApplicationRunner {

    private static final Logger log = LoggerFactory.getLogger(BootstrapAdmin.class);
    private final UserRepository users;
    private final PasswordEncoder passwordEncoder;
    private final AppProperties properties;

    public BootstrapAdmin(UserRepository users, PasswordEncoder passwordEncoder, AppProperties properties) {
        this.users = users;
        this.passwordEncoder = passwordEncoder;
        this.properties = properties;
    }

    @Override
    public void run(ApplicationArguments args) {
        String username = properties.getBootstrap().getAdminUsername().trim().toLowerCase();
        if (users.existsByUsernameIgnoreCase(username)) {
            return;
        }
        UserAccount admin = new UserAccount(
                username,
                passwordEncoder.encode(properties.getBootstrap().getAdminPassword()),
                UserRole.ADMIN);
        users.save(admin);
        log.warn("Created bootstrap admin '{}'; replace the development password before deployment", username);
    }
}
