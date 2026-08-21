package com.aioagent.business.config;

import com.aioagent.business.common.TraceIdFilter;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.List;
import javax.crypto.SecretKey;
import javax.crypto.spec.SecretKeySpec;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.config.annotation.method.configuration.EnableMethodSecurity;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.oauth2.jose.jws.MacAlgorithm;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.security.oauth2.jwt.JwtEncoder;
import org.springframework.security.oauth2.jwt.NimbusJwtDecoder;
import org.springframework.security.oauth2.jwt.NimbusJwtEncoder;
import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationConverter;
import org.springframework.security.web.SecurityFilterChain;

@Configuration(proxyBeanMethods = false)
@EnableMethodSecurity
public class SecurityConfig {

    @Bean
    SecurityFilterChain securityFilterChain(HttpSecurity http) throws Exception {
        JwtAuthenticationConverter converter = new JwtAuthenticationConverter();
        converter.setJwtGrantedAuthoritiesConverter(jwt -> {
            String role = jwt.getClaimAsString("role");
            return role == null ? List.of() : List.of(new SimpleGrantedAuthority("ROLE_" + role));
        });

        http
                .csrf(csrf -> csrf.disable())
                .sessionManagement(session -> session.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
                .authorizeHttpRequests(authorize -> authorize
                        .requestMatchers("/api/v1/auth/config", "/api/v1/auth/register", "/api/v1/auth/login").permitAll()
                        .requestMatchers("/internal/v1/**").permitAll()
                        .requestMatchers("/actuator/health", "/actuator/info").permitAll()
                        .requestMatchers("/actuator/**").hasRole("ADMIN")
                        .anyRequest().authenticated())
                .exceptionHandling(exceptions -> exceptions
                        .authenticationEntryPoint((request, response, exception) -> writeSecurityError(
                                request,
                                response,
                                HttpServletResponse.SC_UNAUTHORIZED,
                                "UNAUTHORIZED",
                                "请先登录"))
                        .accessDeniedHandler((request, response, exception) -> writeSecurityError(
                                request,
                                response,
                                HttpServletResponse.SC_FORBIDDEN,
                                "FORBIDDEN",
                                "无访问权限")))
                .oauth2ResourceServer(oauth2 -> oauth2
                        .authenticationEntryPoint((request, response, exception) -> writeSecurityError(
                                request,
                                response,
                                HttpServletResponse.SC_UNAUTHORIZED,
                                "UNAUTHORIZED",
                                "登录凭证无效或已过期"))
                        .jwt(jwt -> jwt.jwtAuthenticationConverter(converter)));
        return http.build();
    }

    @Bean
    PasswordEncoder passwordEncoder() {
        return new BCryptPasswordEncoder();
    }

    @Bean
    JwtEncoder jwtEncoder(AppProperties properties) {
        return NimbusJwtEncoder.withSecretKey(secretKey(properties)).algorithm(MacAlgorithm.HS256).build();
    }

    @Bean
    JwtDecoder jwtDecoder(AppProperties properties) {
        return NimbusJwtDecoder.withSecretKey(secretKey(properties)).macAlgorithm(MacAlgorithm.HS256).build();
    }

    private SecretKey secretKey(AppProperties properties) {
        String configured = properties.getSecurity().getJwtSecret();
        if (configured == null || configured.isBlank()) {
            throw new IllegalStateException("AIO_JWT_SECRET is required");
        }
        byte[] bytes = configured.getBytes(StandardCharsets.UTF_8);
        if (bytes.length < 32) {
            throw new IllegalStateException("AIO_JWT_SECRET must contain at least 32 bytes");
        }
        return new SecretKeySpec(bytes, "HmacSHA256");
    }

    private void writeSecurityError(
            HttpServletRequest request,
            HttpServletResponse response,
            int status,
            String code,
            String message) throws IOException {
        Object attribute = request.getAttribute(TraceIdFilter.REQUEST_ATTRIBUTE);
        String traceId = attribute == null ? "" : attribute.toString();
        response.setStatus(status);
        response.setCharacterEncoding(StandardCharsets.UTF_8.name());
        response.setContentType("application/json");
        response.getWriter().write("{\"error\":{\"code\":\"" + code
                + "\",\"message\":\"" + message
                + "\",\"trace_id\":\"" + traceId
                + "\",\"details\":[]}}");
    }
}
