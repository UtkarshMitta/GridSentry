"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { AnimatePresence, motion } from "framer-motion";
import { AgentProgress } from "@/components/agent-progress";
import { ReportPanel } from "@/components/report-panel";
import { SiteMap } from "@/components/site-map";
import { Badge, Button, Card, Skeleton, riskTone } from "@/components/ui";
import { eventsUrl, getRun } from "@/lib/api";
import type { PipelineEvent, Run } from "@/lib/types";

type Phase = "connecting" | "running" | "complete" | "error";

export default function RunPage({ params }: { params: { id: string } }) {
  const runId = params.id;
  const [phase, setPhase] = useState<Phase>("connecting");
  const [events, setEvents] = useState<PipelineEvent[]>([]);
  const [run, setRun] = useState<Run | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const sourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function finish() {
      try {
        const full = await getRun(runId);
        if (cancelled) return;
        setRun(full);
        setPhase(full.status === "complete" ? "complete" : "error");
      } catch {
        if (!cancelled) {
          setErrorMsg("Could not load the completed report.");
          setPhase("error");
        }
      }
    }

    async function init() {
      try {
        const existing = await getRun(runId);
        if (cancelled) return;
        if (existing.status === "complete") {
          setRun(existing);
          setPhase("complete");
          return;
        }
        setPhase("running");
        const source = new EventSource(eventsUrl(runId));
        sourceRef.current = source;
        source.onmessage = (msg) => {
          const event: PipelineEvent = JSON.parse(msg.data);
          if (event.type === "complete") {
            source.close();
            finish();
            return;
          }
          if (event.type === "error") {
            source.close();
            setErrorMsg(event.message ?? "The agent pipeline failed.");
            setPhase("error");
            return;
          }
          setEvents((prev) => [...prev, event]);
        };
        source.onerror = () => {
          // EventSource retries automatically; only fail hard if run vanished
        };
      } catch {
        if (!cancelled) {
          setErrorMsg("Run not found. It may have expired after an API restart.");
          setPhase("error");
        }
      }
    }

    init();
    return () => {
      cancelled = true;
      sourceRef.current?.close();
    };
  }, [runId]);

  return (
    <div className="mx-auto max-w-7xl px-6 py-8">
      <AnimatePresence mode="wait">
        {(phase === "connecting" || phase === "running") && (
          <motion.div
            key="progress"
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -12 }}
            transition={{ duration: 0.35 }}
            className="py-10"
          >
            {phase === "connecting" ? (
              <div className="mx-auto w-full max-w-2xl space-y-3">
                <Skeleton className="h-8 w-2/3" />
                <Skeleton className="h-64 w-full" />
              </div>
            ) : (
              <AgentProgress events={events} />
            )}
          </motion.div>
        )}

        {phase === "error" && (
          <motion.div
            key="error"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="py-16"
          >
            <Card className="mx-auto max-w-md p-8 text-center">
              <div className="mx-auto mb-4 flex h-10 w-10 items-center justify-center rounded-full bg-danger/15 text-danger">
                !
              </div>
              <h2 className="text-base font-semibold text-zinc-100">
                Analysis unavailable
              </h2>
              <p className="mt-2 text-sm text-zinc-500">
                {errorMsg ?? "Something went wrong running the assessment."}
              </p>
              <Link href="/" className="mt-6 inline-block">
                <Button variant="outline">Start a new analysis</Button>
              </Link>
            </Card>
          </motion.div>
        )}

        {phase === "complete" && run?.gis && run.report && (
          <motion.div
            key="results"
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.45, ease: "easeOut" }}
          >
            {/* Header */}
            <div className="flex flex-wrap items-center justify-between gap-4 pb-6">
              <div>
                <div className="flex flex-wrap items-center gap-3">
                  <h1 className="text-xl font-bold tracking-tight text-zinc-50">
                    {run.gis.site.name}
                  </h1>
                  {run.report.developable ? (
                    <Badge tone={riskTone(run.report.risk_level)} className="uppercase">
                      {run.report.risk_level} risk · {run.report.risk_score}/100
                    </Badge>
                  ) : (
                    <Badge tone="danger" className="uppercase">
                      ⛔ Not viable ·{" "}
                      {run.report.land_status.category === "urban_built"
                        ? "no buildable land"
                        : run.report.land_status.category === "open_water"
                          ? "open water"
                          : "federal land"}
                    </Badge>
                  )}
                  {(() => {
                    const j = run.gis.site.jurisdiction;
                    const where = j.state
                      ? [j.county, j.state].filter(Boolean).join(", ")
                      : "Jurisdiction unresolved";
                    return (
                      <Badge tone={j.verified ? "accent" : "danger"} title={`Resolved via ${j.method}`}>
                        {j.verified ? "✓ " : "⚠ "}
                        {where}
                        {j.verified ? " (verified)" : " (unverified)"}
                      </Badge>
                    );
                  })()}
                </div>
                <p className="mt-1 font-mono text-xs text-zinc-500">
                  {run.gis.site.lat.toFixed(4)}, {run.gis.site.lon.toFixed(4)} ·{" "}
                  {run.gis.site.acreage} ac · {run.gis.site.project_type} ·{" "}
                  {new Date(run.report.generated_at).toLocaleString()}
                </p>
                {run.report.developable && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {(
                      [
                        ["wetlands", "NWI wetlands"],
                        ["species", "IPaC species"],
                        ["flood", "FEMA flood"],
                        ["protected", "PAD-US"],
                      ] as const
                    ).map(([key, label]) => {
                      const state = run.gis!.provenance[key];
                      const tone =
                        state === "live" ? "accent" : state === "simulated" ? "danger" : "amber";
                      const mark = state === "live" ? "● live" : state === "simulated" ? "▲ simulated" : "○ n/a";
                      return (
                        <Badge key={key} tone={tone as "accent" | "danger" | "amber"} className="text-[10px]">
                          {label}: {mark}
                        </Badge>
                      );
                    })}
                  </div>
                )}
              </div>
              <div className="flex gap-2">
                <a href={`/api/pdf/${runId}`} target="_blank" rel="noreferrer">
                  <Button>
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                      <path
                        d="M12 3v11m0 0l-4-4m4 4l4-4M5 19h14"
                        stroke="currentColor"
                        strokeWidth="2"
                        strokeLinecap="round"
                      />
                    </svg>
                    Export PDF
                  </Button>
                </a>
                <Link href="/">
                  <Button variant="outline">New analysis</Button>
                </Link>
              </div>
            </div>

            {/* Not-viable banner (Land Status Gate tripped) */}
            {!run.report.developable && (
              <motion.div
                initial={{ opacity: 0, y: -6 }}
                animate={{ opacity: 1, y: 0 }}
                className="mb-5 flex items-start gap-3 rounded-xl border border-danger/40 bg-danger/[0.08] px-5 py-4"
              >
                <span className="mt-0.5 text-lg leading-none text-danger">⛔</span>
                {run.report.land_status.category === "federal_protected" ? (
                  <div>
                    <p className="text-sm font-semibold text-danger">
                      Development not legally possible at this location
                    </p>
                    <p className="mt-1 text-[13px] leading-relaxed text-zinc-400">
                      The Land Status Gate placed this site inside{" "}
                      <span className="font-medium text-zinc-200">
                        {run.report.land_status.unit_name}
                      </span>{" "}
                      ({run.report.land_status.designation}, managed by{" "}
                      {run.report.land_status.manager}). The standard wetland, species, and
                      floodplain assessment was intentionally skipped — no permitting path exists
                      for utility-scale development on this land.{" "}
                      {run.report.land_status.verified ? (
                        <span className="text-accent">Verified against USGS PAD-US.</span>
                      ) : (
                        <span className="text-amber">
                          Flagged from offline reference — confirm against PAD-US.
                        </span>
                      )}
                    </p>
                  </div>
                ) : (
                  <div>
                    <p className="text-sm font-semibold text-danger">
                      {run.report.land_status.category === "open_water"
                        ? "No land at these coordinates"
                        : "No buildable land at these coordinates"}
                    </p>
                    <p className="mt-1 text-[13px] leading-relaxed text-zinc-400">
                      The Land Status Gate found the proposed {run.gis.site.acreage}-acre footprint
                      sits on{" "}
                      <span className="font-medium text-zinc-200">
                        {run.report.land_status.category === "open_water"
                          ? "open water"
                          : "fully built-up urban land"}
                      </span>
                      {run.report.land_status.land_cover_checked && (
                        <>
                          {" "}
                          (NLCD 2021: dominant cover {run.report.land_status.dominant_cover},{" "}
                          {Math.round((run.report.land_status.high_intensity_fraction ?? 0) * 100)}%
                          medium/high-intensity developed)
                        </>
                      )}
                      . A greenfield {run.gis.site.project_type} project of this size cannot
                      physically exist here, so the wetland, species, and floodplain assessment was
                      intentionally skipped.{" "}
                      {run.report.land_status.land_cover_checked ? (
                        <span className="text-accent">
                          Verified against USGS/MRLC NLCD land cover.
                        </span>
                      ) : (
                        <span className="text-amber">
                          Flagged from offline reference — confirm against NLCD.
                        </span>
                      )}
                    </p>
                  </div>
                )}
              </motion.div>
            )}

            {/* Split layout */}
            <div className="grid gap-5 lg:grid-cols-[1fr_1fr] xl:grid-cols-[1.1fr_1fr]">
              <div className="lg:sticky lg:top-20 lg:self-start">
                <Card className="overflow-hidden">
                  <div className="flex items-center justify-between border-b border-edge px-4 py-2.5">
                    <span className="text-xs font-medium text-zinc-400">
                      Risk zone overlay
                    </span>
                    <div className="flex items-center gap-3 text-[10.5px] text-zinc-500">
                      <span className="flex items-center gap-1">
                        <span className="h-2 w-2 rounded-sm bg-danger/70" /> Protected wetland
                      </span>
                      <span className="flex items-center gap-1">
                        <span className="h-2 w-2 rounded-sm bg-amber/70" /> Habitat / NWI
                      </span>
                      <span className="flex items-center gap-1">
                        <span className="h-2 w-2 rounded-sm bg-accent/70" /> Alt. route
                      </span>
                    </div>
                  </div>
                  <div className="h-[420px] lg:h-[calc(100vh-13rem)]">
                    <SiteMap
                      center={[run.gis.site.lat, run.gis.site.lon]}
                      zoom={14}
                      marker={[run.gis.site.lat, run.gis.site.lon]}
                      gis={run.gis}
                      altRoute={run.report.alternatives[0]?.geometry ?? null}
                    />
                  </div>
                </Card>
              </div>

              <div className="scroll-slim lg:max-h-[calc(100vh-9rem)] lg:overflow-y-auto lg:pr-1">
                <ReportPanel report={run.report} />
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
