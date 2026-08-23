import { afterEach, describe, expect, it, vi } from "vitest";

import {
  actOnCandidate,
  apiHealth,
  createIdentificationCase,
  getDataQualityIssues,
  getImportRuns,
  exportDataQualityIssues,
  resolveDataQualityIssue,
  searchParts,
} from "./api";

afterEach(() => {
  vi.restoreAllMocks();
});

function mockResponse({ ok = true, status = 200, body = "" } = {}) {
  return Promise.resolve({
    ok,
    status,
    text: () => Promise.resolve(body),
  });
}

describe("api helpers", () => {
  it("parses successful JSON responses", async () => {
    vi.stubGlobal("fetch", vi.fn(() => mockResponse({ body: JSON.stringify({ ok: true, results: [] }) })));

    const response = await searchParts("filter", 3);

    expect(response).toEqual({ ok: true, results: [] });
  });

  it("throws backend errors for non-2xx responses", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => mockResponse({ ok: false, status: 503, body: JSON.stringify({ detail: "Image index missing" }) })),
    );

    await expect(apiHealth()).rejects.toThrow("Image index missing");
  });

  it("throws a clear error for malformed JSON", async () => {
    vi.stubGlobal("fetch", vi.fn(() => mockResponse({ ok: false, status: 500, body: "<html>broken</html>" })));

    await expect(apiHealth()).rejects.toThrow("<html>broken</html>");
  });

  it("submits multiple image identification cases", async () => {
    const fetchMock = vi.fn(() => mockResponse({ body: JSON.stringify({ ok: true, candidates: [] }) }));
    vi.stubGlobal("fetch", fetchMock);
    const files = [new File(["a"], "a.jpg", { type: "image/jpeg" }), new File(["b"], "b.jpg", { type: "image/jpeg" })];

    await createIdentificationCase({ manufacturer: "GE Healthcare", files, top_k: 3 });

    const [, options] = fetchMock.mock.calls[0];
    expect(options.method).toBe("POST");
    expect(options.body.getAll("files")).toHaveLength(2);
    expect(options.body.get("manufacturer")).toBe("GE Healthcare");
  });

  it("records candidate actions", async () => {
    const fetchMock = vi.fn(() => mockResponse({ body: JSON.stringify({ ok: true, status: "verified_match" }) }));
    vi.stubGlobal("fetch", fetchMock);

    await actOnCandidate(1, 2, "confirm", "nk", "matches label");

    const [, options] = fetchMock.mock.calls[0];
    expect(options.method).toBe("POST");
    expect(JSON.parse(options.body).action).toBe("confirm");
  });

  it("calls protected data review endpoints with the admin key", async () => {
    const fetchMock = vi.fn(() => mockResponse({ body: JSON.stringify({ ok: true, runs: [] }) }));
    vi.stubGlobal("fetch", fetchMock);

    await getImportRuns("secret");

    const [, options] = fetchMock.mock.calls[0];
    expect(options.headers["X-AIBE-API-Key"]).toBe("secret");
  });

  it("passes data-quality filters through query params", async () => {
    const fetchMock = vi.fn(() => mockResponse({ body: JSON.stringify({ ok: true, issues: [] }) }));
    vi.stubGlobal("fetch", fetchMock);

    await getDataQualityIssues("secret", { status: "open", issue_type: "duplicate_part_conflicting_description" });

    const [url] = fetchMock.mock.calls[0];
    expect(url).toContain("status=open");
    expect(url).toContain("issue_type=duplicate_part_conflicting_description");
  });

  it("records data-quality issue resolutions", async () => {
    const fetchMock = vi.fn(() => mockResponse({ body: JSON.stringify({ ok: true, issue: { id: 7 } }) }));
    vi.stubGlobal("fetch", fetchMock);

    await resolveDataQualityIssue("secret", 7, {
      status: "accepted_as_distinct",
      resolution_selected: "accepted_as_distinct",
      resolution_notes: "fixture review",
      resolved_by: "nk",
    });

    const [, options] = fetchMock.mock.calls[0];
    expect(options.method).toBe("POST");
    expect(options.headers["X-AIBE-API-Key"]).toBe("secret");
    expect(JSON.parse(options.body).resolved_by).toBe("nk");
  });

  it("exports data-quality issues with the admin key", async () => {
    const fetchMock = vi.fn(() => mockResponse({ body: "id,status\n1,open\n" }));
    vi.stubGlobal("fetch", fetchMock);

    const csv = await exportDataQualityIssues("secret", { status: "open" });

    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toContain("format=csv");
    expect(options.headers["X-AIBE-API-Key"]).toBe("secret");
    expect(csv).toContain("id,status");
  });
});
