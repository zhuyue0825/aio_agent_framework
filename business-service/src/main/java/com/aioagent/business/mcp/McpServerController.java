package com.aioagent.business.mcp;

import com.aioagent.business.auth.CurrentUser;
import com.aioagent.business.auth.UserAccount;
import jakarta.validation.Valid;
import java.util.Map;
import java.util.UUID;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/mcp/servers")
public class McpServerController {

    private final CurrentUser currentUser;
    private final McpServerService servers;

    public McpServerController(CurrentUser currentUser, McpServerService servers) {
        this.currentUser = currentUser;
        this.servers = servers;
    }

    @GetMapping
    public McpServerDtos.ListResponse list(Authentication authentication) {
        return servers.list(currentUser.require(authentication));
    }

    @PutMapping("/qq-mail")
    public McpServerDtos.ServerResponse connectQqMail(
            Authentication authentication,
            @Valid @RequestBody McpServerDtos.ConnectQqMailRequest request) {
        UserAccount user = currentUser.require(authentication);
        return new McpServerDtos.ServerResponse(servers.connectQqMail(user, request));
    }

    @PostMapping("/{id}/test")
    public McpServerDtos.ServerResponse test(Authentication authentication, @PathVariable UUID id) {
        return new McpServerDtos.ServerResponse(servers.test(currentUser.require(authentication), id));
    }

    @PutMapping("/{id}/enabled")
    public McpServerDtos.ServerResponse setEnabled(
            Authentication authentication,
            @PathVariable UUID id,
            @Valid @RequestBody McpServerDtos.EnabledRequest request) {
        return new McpServerDtos.ServerResponse(
                servers.setEnabled(currentUser.require(authentication), id, request.enabled()));
    }

    @DeleteMapping("/{id}")
    public Map<String, Boolean> delete(Authentication authentication, @PathVariable UUID id) {
        servers.delete(currentUser.require(authentication), id);
        return Map.of("ok", true);
    }
}
