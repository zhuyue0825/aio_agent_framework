import { afterEach, expect, it, vi } from "vitest";
import { api, ApiError } from "../api";
import { probeProjectAvailability } from "../projectAvailability";

afterEach(() => vi.restoreAllMocks());

it("limits concurrent probes and never loads directory trees", async () => {
  let active = 0;
  let peak = 0;
  vi.spyOn(api, "workspaceAvailability").mockImplementation(async () => {
    peak = Math.max(peak, ++active);
    await new Promise((resolve) => setTimeout(resolve, 1));
    active--;
    return { available: true };
  });
  const tree = vi.spyOn(api, "workspaceTree");
  const result = vi.fn();
  await probeProjectAvailability(Array.from({ length: 10 }, (_, i) => String(i)), () => true, result);
  expect(peak).toBe(3);
  expect(result).toHaveBeenCalledTimes(10);
  expect(tree).not.toHaveBeenCalled();
});

it("only hides confirmed unavailable directories and recovers available ones", async () => {
  vi.spyOn(api, "workspaceAvailability").mockImplementation(async (id) => {
    if (id === "missing") throw new ApiError("missing", 400, "WORKSPACE_ERROR");
    if (id === "offline") throw new ApiError("offline", 502, "AGENT_SERVICE_ERROR");
    if (id === "network") throw new TypeError("Failed to fetch");
    return { available: true };
  });
  const result = vi.fn();
  await probeProjectAvailability(["missing", "offline", "network", "restored"], () => true, result);
  expect(result.mock.calls).toEqual([["missing", false], ["restored", true]]);
});

it("discards late results and stops scheduling after logout or a new session", async () => {
  let current = true;
  let release!: (value: { available: boolean }) => void;
  const pending = new Promise<{ available: boolean }>((resolve) => { release = resolve; });
  const probe = vi.spyOn(api, "workspaceAvailability").mockReturnValue(pending);
  const result = vi.fn();
  const work = probeProjectAvailability(["1", "2", "3", "4"], () => current, result);
  current = false;
  release({ available: true });
  await work;
  expect(probe).toHaveBeenCalledTimes(3);
  expect(result).not.toHaveBeenCalled();
});
