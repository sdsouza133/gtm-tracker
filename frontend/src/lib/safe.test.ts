import { safeUrl, strings } from "@/lib/safe";

describe("safe", () => {
  it("keeps only strings", () => {
    expect(strings(["a", 1, { b: 2 }, null, "c"])).toEqual(["a", "c"]);
    expect(strings("a")).toEqual([]);
  });

  it("keeps only http(s) links", () => {
    expect(safeUrl("https://example.com/a")).toBe("https://example.com/a");
    expect(safeUrl("http://example.com")).toBe("http://example.com");
    expect(safeUrl("javascript:alert(1)")).toBeUndefined();
    expect(safeUrl("JavaScript:alert(1)")).toBeUndefined();
    expect(safeUrl("Not found")).toBeUndefined();
    expect(safeUrl(null)).toBeUndefined();
  });
});
