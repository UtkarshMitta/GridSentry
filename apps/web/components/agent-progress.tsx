"use client";

import { AnimatePresence, motion } from "framer-motion";
import type { AgentId, PipelineEvent } from "@/lib/types";
import { Card, cn } from "./ui";

const STAGES: { id: AgentId; title: string; role: string }[] = [
  { id: "system", title: "Data Ingestion", role: "GIS · NWI · ECOS · PAD-US · NFHL" },
  { id: "geolocation", title: "Geolocation Analyst", role: "Spatial conflict detection" },
  { id: "legal", title: "Legal Compliance Officer", role: "NEPA · CWA · ESA · state law" },
  { id: "critic", title: "Red-Team Critic", role: "Adversarial review & stop-work scan" },
];

type StageState = "idle" | "active" | "done";

function stageStates(events: PipelineEvent[]): Record<AgentId, StageState> {
  const states: Record<AgentId, StageState> = {
    system: "idle",
    geolocation: "idle",
    legal: "idle",
    critic: "idle",
  };
  for (const e of events) {
    if (!e.agent) continue;
    if (e.type === "gis" || e.state === "done") states[e.agent] = "done";
    else if (states[e.agent] !== "done") states[e.agent] = "active";
  }
  return states;
}

export function AgentProgress({ events }: { events: PipelineEvent[] }) {
  const states = stageStates(events);
  const progress = events.length
    ? Math.max(...events.map((e) => e.progress ?? 0))
    : 0;
  const lastByAgent = new Map<AgentId, string>();
  for (const e of events) {
    if (e.agent && e.message) lastByAgent.set(e.agent, e.message);
  }

  return (
    <Card className="mx-auto w-full max-w-2xl p-6">
      <div className="flex items-center justify-between pb-1">
        <h2 className="text-sm font-semibold text-zinc-100">
          Multi-agent assessment in progress
        </h2>
        <span className="font-mono text-xs text-accent">
          {Math.round(progress * 100)}%
        </span>
      </div>
      <div className="mb-6 h-1 overflow-hidden rounded-full bg-white/[0.06]">
        <motion.div
          className="h-full rounded-full bg-accent"
          animate={{ width: `${progress * 100}%` }}
          transition={{ ease: "easeOut", duration: 0.5 }}
        />
      </div>

      <ol className="space-y-1">
        {STAGES.map((stage) => {
          const state = states[stage.id];
          const message = lastByAgent.get(stage.id);
          return (
            <li
              key={stage.id}
              className={cn(
                "rounded-lg px-3 py-3 transition-colors duration-300",
                state === "active" && "bg-accent/[0.06]",
              )}
            >
              <div className="flex items-center gap-3">
                <span className="relative flex h-5 w-5 items-center justify-center">
                  {state === "done" ? (
                    <motion.svg
                      initial={{ scale: 0.5, opacity: 0 }}
                      animate={{ scale: 1, opacity: 1 }}
                      width="18"
                      height="18"
                      viewBox="0 0 24 24"
                      fill="none"
                      className="text-accent"
                    >
                      <circle cx="12" cy="12" r="10" fill="currentColor" opacity="0.15" />
                      <path
                        d="M8 12.5l2.6 2.6L16 9.5"
                        stroke="currentColor"
                        strokeWidth="2"
                        strokeLinecap="round"
                      />
                    </motion.svg>
                  ) : state === "active" ? (
                    <>
                      <span className="absolute h-4 w-4 rounded-full bg-accent/20 animate-ping" />
                      <span className="h-2 w-2 rounded-full bg-accent" />
                    </>
                  ) : (
                    <span className="h-2 w-2 rounded-full bg-zinc-700" />
                  )}
                </span>
                <div className="flex flex-1 items-baseline justify-between">
                  <span
                    className={cn(
                      "text-sm font-medium",
                      state === "idle" ? "text-zinc-600" : "text-zinc-100",
                    )}
                  >
                    {stage.title}
                  </span>
                  <span className="text-[11px] text-zinc-600">{stage.role}</span>
                </div>
              </div>
              <AnimatePresence mode="wait">
                {state === "active" && message && (
                  <motion.p
                    key={message}
                    initial={{ opacity: 0, y: 3 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -3 }}
                    transition={{ duration: 0.25 }}
                    className="pl-8 pt-1.5 font-mono text-xs text-accent/80"
                  >
                    {message}
                  </motion.p>
                )}
                {state === "done" && message && (
                  <motion.p
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    className="pl-8 pt-1.5 text-xs text-zinc-500"
                  >
                    {message}
                  </motion.p>
                )}
              </AnimatePresence>
            </li>
          );
        })}
      </ol>
    </Card>
  );
}
