import { daysBetween, formatDateTimeDay, formatDay, initials, nextWorkday, relativeDay } from "@/lib/format";

describe("dates", () => {
  it("reads API days as calendar days", () => {
    expect(formatDay("2026-10-26")).toBe("Mon, Oct 26");
    expect(daysBetween("2026-10-26", "2026-11-02")).toBe(7);
  });

  it("never puts 'later' on a weekend", () => {
    expect(nextWorkday("2026-10-28")).toBe("2026-10-29");
    expect(nextWorkday("2026-10-30")).toBe("2026-11-02"); // Friday -> Monday
    expect(nextWorkday("2026-10-31")).toBe("2026-11-02"); // Saturday -> Monday
  });

  it("says days in words", () => {
    expect(relativeDay("2026-10-26", "2026-10-26")).toBe("today");
    expect(relativeDay("2026-10-27", "2026-10-26")).toBe("tomorrow");
    expect(relativeDay("2026-10-29", "2026-10-26")).toBe("in 3 days");
    expect(relativeDay("2026-10-24", "2026-10-26")).toBe("2 days ago");
  });

  it("makes initials", () => {
    expect(initials("Priya  Raman Example")).toBe("PR");
  });
});

describe("timestamps", () => {
  it("uses the local day of a timestamp, not its UTC date", () => {
    const evening = new Date(2026, 9, 26, 21, 30); // 9:30 PM local, Oct 26
    expect(formatDateTimeDay(evening.toISOString())).toBe("Mon, Oct 26");
  });
});
