import { describe, expect, it } from "vitest";

import { buildBackendLogParams } from "../logs";

describe("buildBackendLogParams", () => {
  it("includes provided pagination and filter values", () => {
    const params = buildBackendLogParams({
      page: 2,
      pageSize: 100,
      level: "ERROR",
      event: "job.failed",
      strategyId: "strat-1",
      logger: "app.worker",
      search: "failure",
      startTime: "2025-10-11T12:00:00.000Z",
      endTime: "2025-10-11T13:00:00.000Z"
    });

    expect(params).toMatchObject({
      page: 2,
      page_size: 100,
      level: "ERROR",
      event: "job.failed",
      strategyId: "strat-1",
      logger: "app.worker",
      search: "failure",
      startTime: "2025-10-11T12:00:00.000Z",
      endTime: "2025-10-11T13:00:00.000Z"
    });
  });

  it("omits nullish filter values", () => {
    const params = buildBackendLogParams({
      page: 1,
      pageSize: 50,
      level: null,
      event: null,
      strategyId: null,
      logger: null,
      search: null,
      startTime: null,
      endTime: null
    });

    expect(params).toMatchObject({
      page: 1,
      page_size: 50
    });
    expect(Object.keys(params)).not.toEqual(
      expect.arrayContaining(["level", "event", "strategyId", "logger", "search", "startTime", "endTime"])
    );
  });
});
