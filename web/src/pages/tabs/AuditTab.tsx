import { useQuery } from "@tanstack/react-query";
import { Empty, ErrorNote, Loading, Panel } from "../../components/ui";
import { useApi } from "../../lib/api";
import { dateTime } from "../../lib/format";
import type { AuditRow } from "../../lib/types";
import type { Workspace } from "../ClientWorkspace";
import { describe } from "./ReviewTab";

export default function AuditTab({ ws }: { ws: Workspace }) {
  const api = useApi();
  const rows = useQuery({ queryKey: ["audit", ws.portfolio.id], queryFn: () => api<AuditRow[]>(`/audit?portfolio_id=${ws.portfolio.id}`) });
  if (rows.isLoading) return <Loading />;
  return (
    <Panel title="Audit trail" tag="Append-only · this version">
      <ErrorNote error={rows.error} />
      {rows.data?.length === 0 ? (
        <Empty>No activity on this version yet.</Empty>
      ) : (
        <div className="overflow-x-auto">
          <table className="data">
            <thead><tr><th>When</th><th>What</th><th>Engine</th><th>Model</th><th>Checked</th></tr></thead>
            <tbody>
              {rows.data?.map((r, i) => (
                <tr key={i}>
                  <td className="whitespace-nowrap">{dateTime(r.timestamp)}</td>
                  <td>{describe(r)}</td>
                  <td className="figure">v{r.engine_version}</td>
                  <td className="figure">{r.model ?? "—"}</td>
                  <td>{r.verified === null || r.verified === undefined ? "—" : r.verified ? "✓ verified" : "✗ withheld"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="mt-3 text-xs text-muted">Every output is logged with its inputs, so you can show how a recommendation was reached. Entries can't be edited or deleted.</p>
    </Panel>
  );
}
