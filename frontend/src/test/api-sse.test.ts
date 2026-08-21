import { expect, it, vi } from "vitest";
import { api } from "../api";

function responseWithReads(reads: Array<() => Promise<{ value?: Uint8Array; done: boolean }>>) {
  let index = 0;
  return {
    ok: true,
    status: 200,
    headers: new Headers({ "Content-Type": "text/event-stream" }),
    body: {
      getReader: () => ({ read: () => reads[index++]() }),
    },
  } as unknown as Response;
}

it("reconnects SSE with Last-Event-ID and does not replay old events", async () => {
  const encoder = new TextEncoder();
  const first = responseWithReads([
    async () => ({
      value: encoder.encode('data: {"id":1,"run_id":"r1","event_type":"agent.token.delta","payload":{"delta":"你"},"created_at":"now"}\n\n'),
      done: false,
    }),
    async () => {
      throw new Error("connection reset");
    },
  ]);
  const second = responseWithReads([
    async () => ({
      value: encoder.encode('data: {"id":2,"run_id":"r1","event_type":"run.succeeded","payload":{},"created_at":"now"}\n\n'),
      done: false,
    }),
    async () => ({ done: true }),
  ]);
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(first).mockResolvedValueOnce(second);
  const received: number[] = [];

  await api.streamRunEvents("r1", (event) => received.push(event.id));

  expect(received).toEqual([1, 2]);
  expect((fetchMock.mock.calls[1][1]?.headers as Record<string, string>)["Last-Event-ID"]).toBe("1");
});
