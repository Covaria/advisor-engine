import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { ComparisonTable, Empty, ErrorNote, Loading, Panel } from "../../components/ui";
import { useApi } from "../../lib/api";
import { pct, signed } from "../../lib/format";
import type { CompareResult } from "../../lib/types";
import { versionName, type Workspace } from "../ClientWorkspace";

export default function CompareTab({ ws }: { ws: Workspace }) {
  const api = useApi();
  const all = ws.portfolios;
  // Default to the version before the one being viewed (or, for the first, the next one).
  const at = all.findIndex((p) => p.id === ws.portfolio.id);
  const [a, setA] = useState(at > 0 ? all[at - 1].id : all[0].id);
  const [b, setB] = useState(at > 0 ? all[at].id : (all[1] ?? all[0]).id);
  const result = useQuery({
    queryKey: ["compare", a, b],
    queryFn: () => api<CompareResult>(`/portfolios/${a}/compare/${b}`),
    enabled: a !== b,
  });

  if (all.length < 2) {
    return <Empty>Compare needs two versions. Upload new holdings or save a what-if from the Holdings tab.</Empty>;
  }
  const pick = (value: string, set: (v: string) => void, label: string) => (
    <label className="text-sm">
      <span className="eyebrow mb-1 block !text-muted">{label}</span>
      <select className="input" value={value} onChange={(e) => set(e.target.value)}>
        {all.map((p) => <option key={p.id} value={p.id}>{versionName(p, all)}</option>)}
      </select>
    </label>
  );

  return (
    <div className="space-y-5">
      <div className="grid gap-3 sm:grid-cols-2">
        {pick(a, setA, "Before")}
        {pick(b, setB, "After")}
      </div>
      {a === b && <Empty>Pick two different versions.</Empty>}
      {result.isLoading && <Loading what="Running the engine on both versions" />}
      <ErrorNote error={result.error} />
      {result.data && (
        <div className="grid gap-5 lg:grid-cols-2">
          <Panel title="Headline figures">
            <ComparisonTable rows={result.data.comparison.headline} />
            <p className="mt-3 text-sm text-muted">
              {result.data.comparison.added.length > 0 && <>Added: {result.data.comparison.added.join(", ")}. </>}
              {result.data.comparison.removed.length > 0 && <>Removed: {result.data.comparison.removed.join(", ")}.</>}
            </p>
          </Panel>
          <Panel title="Sector exposure">
            <table className="data">
              <thead><tr><th>Sector</th><th className="num">Before</th><th className="num">After</th><th className="num">Change</th></tr></thead>
              <tbody>
                {result.data.comparison.sectors.map((s) => (
                  <tr key={s.sector}><td>{s.sector}</td><td className="num">{pct(s.before)}</td>
                    <td className="num">{pct(s.after)}</td><td className="num">{signed(pct(s.change), s.change)}</td></tr>
                ))}
              </tbody>
            </table>
          </Panel>
        </div>
      )}
    </div>
  );
}
