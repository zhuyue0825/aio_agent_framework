package com.aioagent.business.run;

import com.aioagent.business.agent.AgentServiceClient;
import com.aioagent.business.agent.AgentServiceException;
import com.aioagent.business.auth.UserAccount;
import com.aioagent.business.common.ApiException;
import java.util.List;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;

@Service
public class WorkspaceChangeService {

    private final AgentRunService runs;
    private final AgentServiceClient agentService;

    public WorkspaceChangeService(AgentRunService runs, AgentServiceClient agentService) {
        this.runs = runs;
        this.agentService = agentService;
    }

    public AgentRun apply(UserAccount user, UUID runId) {
        AgentRunService.ChangeApplyClaim claim = runs.claimProposedChanges(user, runId);
        if (claim.alreadyApplied()) {
            return runs.require(user, runId);
        }
        try {
            List<String> changedFiles = agentService.applyWorkspaceChanges(
                    claim.workspaceRoot(),
                    claim.proposedChanges(),
                    claim.workspaceOwnerId(),
                    claim.runId());
            return runs.completeProposedChanges(runId, changedFiles);
        } catch (AgentServiceException exception) {
            runs.failProposedChanges(runId, safeMessage(exception.getErrorCode()));
            if ("WORKSPACE_CHANGED".equals(exception.getErrorCode())) {
                throw new ApiException(HttpStatus.CONFLICT, "WORKSPACE_CHANGED", "文件已发生变化，请重新运行 Agent");
            }
            throw exception;
        } catch (RuntimeException exception) {
            runs.failProposedChanges(runId, "修改写入失败，请重试");
            throw exception;
        }
    }

    private String safeMessage(String code) {
        return switch (code == null ? "" : code) {
            case "WORKSPACE_CHANGED" -> "文件已发生变化，请重新运行 Agent";
            case "WORKSPACE_ERROR" -> "工作区不可用，请检查项目目录";
            default -> "修改写入失败，请重试";
        };
    }
}
