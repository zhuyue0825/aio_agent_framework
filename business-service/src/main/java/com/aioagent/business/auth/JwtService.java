package com.aioagent.business.auth;

import com.aioagent.business.config.AppProperties;
import java.time.Instant;
import java.util.UUID;
import org.springframework.security.oauth2.jose.jws.MacAlgorithm;
import org.springframework.security.oauth2.jwt.JwtClaimsSet;
import org.springframework.security.oauth2.jwt.JwtEncoder;
import org.springframework.security.oauth2.jwt.JwtEncoderParameters;
import org.springframework.security.oauth2.jwt.JwsHeader;
import org.springframework.stereotype.Service;

@Service
public class JwtService {

    private final JwtEncoder encoder;
    private final AppProperties properties;

    public JwtService(JwtEncoder encoder, AppProperties properties) {
        this.encoder = encoder;
        this.properties = properties;
    }

    public Token issue(UserAccount user) {
        Instant now = Instant.now();
        Instant expiresAt = now.plus(properties.getSecurity().getTokenTtl());
        String jwtId = UUID.randomUUID().toString();
        JwtClaimsSet claims = JwtClaimsSet.builder()
                .issuer("aio-agent-business-service")
                .issuedAt(now)
                .expiresAt(expiresAt)
                .subject(user.getId().toString())
                .id(jwtId)
                .claim("username", user.getUsername())
                .claim("role", user.getRole().name())
                .build();
        JwsHeader header = JwsHeader.with(MacAlgorithm.HS256).build();
        String value = encoder.encode(JwtEncoderParameters.from(header, claims)).getTokenValue();
        return new Token(value, expiresAt, jwtId);
    }

    public record Token(String value, Instant expiresAt, String jwtId) {
    }
}
