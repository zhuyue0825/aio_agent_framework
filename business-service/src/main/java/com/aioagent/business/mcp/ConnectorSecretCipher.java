package com.aioagent.business.mcp;

import com.aioagent.business.config.AppProperties;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.Base64;
import javax.crypto.Cipher;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.SecretKeySpec;
import org.springframework.stereotype.Component;

@Component
public class ConnectorSecretCipher {

    private static final String PREFIX = "v1.";
    private static final int IV_LENGTH = 12;
    private static final int TAG_BITS = 128;
    private final SecureRandom random = new SecureRandom();
    private final SecretKeySpec key;

    public ConnectorSecretCipher(AppProperties properties) {
        String configured = properties.getSecurity().getConnectorEncryptionKey();
        String source = configured == null || configured.isBlank()
                ? properties.getSecurity().getJwtSecret()
                : configured;
        if (source == null || source.getBytes(StandardCharsets.UTF_8).length < 32) {
            throw new IllegalStateException(
                    "AIO_CONNECTOR_ENCRYPTION_KEY or AIO_JWT_SECRET must contain at least 32 bytes");
        }
        this.key = new SecretKeySpec(sha256("aio-agent-connector-v1\n" + source), "AES");
    }

    public String encrypt(String plaintext, String context) {
        try {
            byte[] iv = new byte[IV_LENGTH];
            random.nextBytes(iv);
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.ENCRYPT_MODE, key, new GCMParameterSpec(TAG_BITS, iv));
            cipher.updateAAD(context.getBytes(StandardCharsets.UTF_8));
            byte[] ciphertext = cipher.doFinal(plaintext.getBytes(StandardCharsets.UTF_8));
            return PREFIX + Base64.getUrlEncoder().withoutPadding()
                    .encodeToString(ByteBuffer.allocate(iv.length + ciphertext.length).put(iv).put(ciphertext).array());
        } catch (GeneralSecurityException exception) {
            throw new IllegalStateException("Failed to encrypt connector secret", exception);
        }
    }

    public String decrypt(String encoded, String context) {
        if (encoded == null || !encoded.startsWith(PREFIX)) {
            throw new IllegalStateException("Unsupported connector secret format");
        }
        try {
            byte[] combined = Base64.getUrlDecoder().decode(encoded.substring(PREFIX.length()));
            if (combined.length <= IV_LENGTH) {
                throw new IllegalStateException("Invalid connector secret payload");
            }
            byte[] iv = new byte[IV_LENGTH];
            byte[] ciphertext = new byte[combined.length - IV_LENGTH];
            System.arraycopy(combined, 0, iv, 0, IV_LENGTH);
            System.arraycopy(combined, IV_LENGTH, ciphertext, 0, ciphertext.length);
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.DECRYPT_MODE, key, new GCMParameterSpec(TAG_BITS, iv));
            cipher.updateAAD(context.getBytes(StandardCharsets.UTF_8));
            return new String(cipher.doFinal(ciphertext), StandardCharsets.UTF_8);
        } catch (GeneralSecurityException | IllegalArgumentException exception) {
            throw new IllegalStateException("Failed to decrypt connector secret", exception);
        }
    }

    private byte[] sha256(String value) {
        try {
            return MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8));
        } catch (GeneralSecurityException exception) {
            throw new IllegalStateException("SHA-256 is unavailable", exception);
        }
    }
}
