"use client";

import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import type { Report, Severity } from "@/lib/types";
import { CitationBadge } from "./citation-badge";
import { Badge, Card, cn, riskTone } from "./ui";

const SEVERITY_DOT: Record<Severity, string> = {
  high: "bg-danger",
  moderate: "bg-amber",
  low: "bg-accent",
  info: "bg-zinc-500",
};

function citationsFor(report: Report, ids: string[]) {
  return ids
    .map((id) => report.citations.find((c) => c.id === id))
    .filter((c): c is NonNullable<typeof c> => Boolean(c));
}

function CollapsibleSection({
  report,
  sectionId,
  defaultOpen,
}: {
  report: Report;
  sectionId: string;
  defaultOpen: boolean;
}) {
  const section = report.sections.find((s) => s.id === sectionId)!;
  const [open, setOpen] = useState(defaultOpen);
  const notes = report.critic_notes.filter((n) => n.target === section.id);

  return (
    <Card className="overflow-hidden">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between gap-3 px-5 py-4 text-left transition-colors hover:bg-white/[0.02]"
      >
        <div className="flex items-center gap-3">
          <Badge tone={riskTone(section.risk)} className="uppercase">
            {section.risk}
          </Badge>
          <h3 className="text-sm font-semibold text-zinc-100">{section.title}</h3>
        </div>
        <motion.svg
          animate={{ rotate: open ? 180 : 0 }}
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          className="shrink-0 text-zinc-500"
        >
          <path d="M6 9l6 6 6-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
        </motion.svg>
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.25, ease: "easeInOut" }}
            className="overflow-hidden"
          >
            <div className="border-t border-edge px-5 py-4">
              <p className="text-[13px] leading-relaxed text-zinc-400">
                {section.summary}
              </p>

              <div className="mt-4 space-y-4">
                {section.findings.map((f) => (
                  <div key={f.id} className="flex gap-3">
                    <span
                      className={cn(
                        "mt-1.5 h-2 w-2 shrink-0 rounded-full",
                        SEVERITY_DOT[f.severity],
                      )}
                    />
                    <div>
                      <p className="text-[13px] font-medium text-zinc-200">{f.title}</p>
                      <p className="mt-1 text-[13px] leading-relaxed text-zinc-500">
                        {f.detail}
                      </p>
                      {f.citation_ids.length > 0 && (
                        <span className="mt-2 flex flex-wrap gap-1.5">
                          {citationsFor(report, f.citation_ids).map((c) => (
                            <CitationBadge key={c.id} citation={c} />
                          ))}
                        </span>
                      )}
                    </div>
                  </div>
                ))}
              </div>

              {notes.length > 0 && (
                <div className="mt-4 space-y-2">
                  {notes.map((n) => (
                    <div
                      key={n.id}
                      className={cn(
                        "rounded-lg border px-3.5 py-2.5 text-[12.5px] leading-relaxed",
                        n.severity === "blocker"
                          ? "border-danger/30 bg-danger/[0.07] text-zinc-300"
                          : "border-amber/25 bg-amber/[0.06] text-zinc-400",
                      )}
                    >
                      <span
                        className={cn(
                          "mr-2 font-mono text-[10px] font-semibold uppercase tracking-wider",
                          n.severity === "blocker" ? "text-danger" : "text-amber",
                        )}
                      >
                        Red-team · {n.severity}
                      </span>
                      {n.note}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </Card>
  );
}

export function ReportPanel({ report }: { report: Report }) {
  return (
    <div className="space-y-4">
      {/* Executive summary */}
      <Card className="p-5">
        <div className="flex items-center justify-between pb-3">
          <h2 className="text-sm font-semibold text-zinc-100">Executive Summary</h2>
          <span className="text-[11px] text-zinc-600">
            Engine: {report.engine} · Confidence {report.confidence}%
          </span>
        </div>
        <p className="text-[13px] leading-relaxed text-zinc-400">
          {report.executive_summary}
        </p>
      </Card>

      {/* Stop-work risks */}
      {report.stop_work_risks.length > 0 && (
        <Card className="border-danger/30 p-5">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-danger">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none">
              <path
                d="M12 3L2.5 20h19L12 3z"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinejoin="round"
              />
              <path d="M12 10v4.5M12 17.5v.1" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
            </svg>
            Stop-Work Risks
          </h2>
          <div className="mt-3 space-y-3">
            {report.stop_work_risks.map((r) => (
              <div key={r.id} className="rounded-lg bg-danger/[0.06] px-4 py-3">
                <p className="text-[13px] font-medium text-zinc-200">{r.title}</p>
                <p className="mt-1 text-[12.5px] leading-relaxed text-zinc-500">{r.detail}</p>
                <p className="mt-1.5 text-[11.5px] text-danger/80">
                  Trigger: {r.trigger}
                </p>
                {r.citation_ids.length > 0 && (
                  <span className="mt-2 flex flex-wrap gap-1.5">
                    {citationsFor(report, r.citation_ids).map((c) => (
                      <CitationBadge key={c.id} citation={c} />
                    ))}
                  </span>
                )}
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Sections */}
      {report.sections.map((s, i) => (
        <CollapsibleSection key={s.id} report={report} sectionId={s.id} defaultOpen={i === 0} />
      ))}

      {/* Alternatives */}
      {report.alternatives.length > 0 && (
      <Card className="border-accent/25 p-5">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-accent">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none">
            <path
              d="M4 17c4 0 4-10 8-10s4 10 8 10"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
            />
          </svg>
          Recommended Alternatives
        </h2>
        <div className="mt-3 space-y-3">
          {report.alternatives.map((a) => (
            <div key={a.id} className="rounded-lg bg-accent/[0.05] px-4 py-3">
              <p className="text-[13px] font-medium text-zinc-200">{a.title}</p>
              <p className="mt-1 text-[12.5px] leading-relaxed text-zinc-500">
                {a.description}
              </p>
              <p className="mt-1.5 text-[11.5px] text-accent/90">{a.impact_reduction}</p>
            </div>
          ))}
        </div>
      </Card>
      )}

      {/* Full citation registry */}
      <Card className="p-5">
        <h2 className="text-sm font-semibold text-zinc-100">Sources & Citations</h2>
        <ol className="mt-3 space-y-2.5">
          {report.citations.map((c, i) => (
            <li key={c.id} className="flex gap-3 text-[12.5px] leading-relaxed">
              <span className="font-mono text-zinc-600">[{i + 1}]</span>
              <span className="text-zinc-500">
                <a
                  href={c.url}
                  target="_blank"
                  rel="noreferrer"
                  className="font-medium text-zinc-300 transition-colors hover:text-accent"
                >
                  {c.label}
                </a>{" "}
                — {c.title}. <em className="text-zinc-600">{c.source}.</em>
              </span>
            </li>
          ))}
        </ol>
      </Card>
    </div>
  );
}
