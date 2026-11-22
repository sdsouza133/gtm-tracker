import type { S } from "@/api/hooks";
import { Card } from "@/components/ui";

/** The ICP a report was built from, as we read it from the company's website. */
export function IcpCard({ icp }: { icp: S["PublicIcp"] }) {
  const rows: [string, string[]][] = [
    ["Industries", icp.industries],
    ["Company size", icp.company_sizes],
    ["Titles", icp.titles],
    ["Seniority", icp.seniority],
  ];
  return (
    <Card className="flex flex-col gap-2 p-5 text-sm">
      <h2 className="font-semibold">Your ICP, as we read it</h2>
      {icp.sells && <p>{icp.sells}</p>}
      {rows.map(([label, values]) =>
        values.length ? (
          <p key={label} className="text-muted">
            <span className="font-medium text-ink">{label}:</span> {values.join(", ")}
          </p>
        ) : null,
      )}
    </Card>
  );
}
