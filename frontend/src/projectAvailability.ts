import { api, ApiError } from "./api";

// Only confirmed workspace errors hide projects. Service/network failures are transient.
export async function probeProjectAvailability(
  projectIds: string[],
  isCurrent: () => boolean,
  onResult: (projectId: string, available: boolean) => void,
): Promise<void> {
  let cursor = 0;
  async function worker() {
    while (isCurrent() && cursor < projectIds.length) {
      const id = projectIds[cursor++];
      try {
        const result = await api.workspaceAvailability(id);
        if (isCurrent()) onResult(id, result.available);
      } catch (error) {
        if (isCurrent() && error instanceof ApiError && error.code === "WORKSPACE_ERROR") {
          onResult(id, false);
        }
      }
    }
  }
  await Promise.all(Array.from({ length: Math.min(3, projectIds.length) }, () => worker()));
}
