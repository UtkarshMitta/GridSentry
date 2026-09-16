"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { listRuns } from "@/lib/api";
import { pruneRunIds, recentRunIds } from "@/lib/history";
import type { RunSummary } from "@/lib/types";
import { Badge, Card, riskTone } from "./ui";

/** Recent analyses, so earlier reports stay reachable after a reload. */
export function RecentRuns() {
  const [runs, setRuns] = useState<RunSummary[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    const ids = recentRunIds();
    if (!ids.length) {
      setRuns([]);
      return;
    }
    listRuns(6, ids)
      .then((found) => {
        if (cancelled) return;
        pruneRunIds(found);
        setRuns(found);
      })
      .catch(() => !cancelled && setRuns([])); // API down: show nothing rather than an error
    return () => {
      cancelled = true;
    };
  }, []);

  if (!runs?.length) return null;

  return (
    <section className="pb-16" aria-labelledby="recent-runs-heading">
      <h2 id="recent-runs-heading" className="pb-3 text-sm font-semibold text-zinc-300">
        Your recent analyses
      </h2>
      <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
        {runs.map((run) => (
          <Link key={run.id} href={`/runs/${run.id}`} className="group">
            <Card className="h-full p-4 transition-colors duration-200 hover:border-accent/30">
              <div className="flex items-start justify-between gap-3">
                <span className="text-[13px] font-medium text-zinc-200 group-hover:text-zinc-100">
                  {run.name}
                </span>
                {run.verdict === "not_viable" ? (
                  <Badge tone="danger" className="shrink-0 uppercase">
                    ⛔ not viable
                  </Badge>
                ) : run.status === "complete" && run.risk_level ? (
                  <Badge tone={riskTone(run.risk_level)} className="shrink-0 uppercase">
                    {run.risk_level} · {run.risk_score}
                  </Badge>
                ) : (
                  <Badge tone={run.status === "error" ? "danger" : "neutral"} className="shrink-0 uppercase">
                    {run.status === "error" ? "failed" : "running"}
                  </Badge>
                )}
              </div>
              <p className="mt-1.5 font-mono text-[11px] text-zinc-500">
                {run.lat.toFixed(4)}, {run.lon.toFixed(4)} · {run.project_type}
              </p>
              <p className="mt-0.5 text-[11px] text-zinc-600">
                {new Date(run.created_at).toLocaleString()}
              </p>
            </Card>
          </Link>
        ))}
      </div>
    </section>
  );
}
