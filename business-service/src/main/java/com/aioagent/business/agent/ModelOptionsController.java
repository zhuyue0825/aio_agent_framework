package com.aioagent.business.agent;

import com.aioagent.business.auth.CurrentUser;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/model-options")
public class ModelOptionsController {

    private final CurrentUser currentUser;
    private final ModelOptionsService options;

    public ModelOptionsController(CurrentUser currentUser, ModelOptionsService options) {
        this.currentUser = currentUser;
        this.options = options;
    }

    @GetMapping
    public ModelOptionsService.Response get(Authentication authentication) {
        return options.options(currentUser.require(authentication));
    }
}
