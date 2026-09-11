"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import { API_URL, createRun, parseCoordinates } from "@/lib/api";
import type { ProjectType } from "@/lib/types";
import { Button, cn } from "./ui";

const PROJECT_TYPES: { id: ProjectType; label: string; icon: string }[] = [
  { id: "solar", label: "Solar", icon: "☀" },
  { id: "wind", label: "Wind", icon: "⌁" },
  { id: "transmission", label: "Transmission", icon: "⚡" },
];

const DEMO_COORDS = "42.9000, -74.3000";

export function CoordinateInput({
  picked,
}: {
  picked?: { lat: number; lon: number } | null;
}) {
  const router = useRouter();
  const [raw, setRaw] = useState("");
  const [projectType, setProjectType] = useState<ProjectType>("solar");
  const [acreage, setAcreage] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // Map click fills the input
  useEffect(() => {
    if (!picked) return;
    setRaw(`${picked.lat.toFixed(4)}, ${picked.lon.toFixed(4)}`);
    setError(null);
  }, [picked]);

  async function submit() {
    setError(null);
    const coords = parseCoordinates(raw);
    if (!coords) {
      setError("Enter coordinates as decimal degrees, e.g. 42.9000, -74.3000");
      return;
    }
    const acres = acreage.trim() ? Number(acreage) : undefined;
    if (acres !== undefined && !(acres > 0 && acres <= 50000)) {
      setError("Acreage must be a number between 1 and 50,000 (or leave it blank).");
      return;
    }
    setSubmitting(true);
    try {
      const { run_id } = await createRun({ ...coords, project_type: projectType, acreage: acres });
      router.push(`/runs/${run_id}`);
    } catch {
      setError(`Could not reach the analysis engine at ${API_URL}. Is the API running?`);
      setSubmitting(false);
    }
  }

  return (
    <div className="w-full max-w-xl">
      <div className="flex flex-wrap items-center gap-1.5 pb-3">
        {PROJECT_TYPES.map((p) => (
          <button
            key={p.id}
            onClick={() => setProjectType(p.id)}
            className={cn(
              "rounded-full border px-3.5 py-1.5 text-xs font-medium transition-all duration-150",
              projectType === p.id
                ? "border-accent/50 bg-accent/15 text-accent"
                : "border-edge bg-surface text-zinc-500 hover:border-white/20 hover:text-zinc-300",
            )}
          >
            <span className="mr-1.5 opacity-80">{p.icon}</span>
            {p.label}
          </button>
        ))}
        <label className="ml-auto flex items-center gap-1.5 text-xs text-zinc-500">
          Footprint
          <input
            value={acreage}
            onChange={(e) => {
              setAcreage(e.target.value);
              setError(null);
            }}
            inputMode="decimal"
            placeholder="300"
            aria-label="Project footprint in acres (optional)"
            className="h-7 w-16 rounded-md border border-edge bg-surface px-2 text-right text-xs text-zinc-100 placeholder:text-zinc-600 focus:border-accent/50 focus:outline-none"
          />
          acres
        </label>
      </div>

      <div
        className={cn(
          "flex items-center gap-2 rounded-xl border bg-surface p-2 shadow-card transition-colors",
          error ? "border-danger/50" : "border-edge focus-within:border-accent/50",
        )}
      >
        <svg
          width="18"
          height="18"
          viewBox="0 0 24 24"
          fill="none"
          className="ml-2 shrink-0 text-zinc-500"
        >
          <path
            d="M12 21s-7-5.1-7-11a7 7 0 1114 0c0 5.9-7 11-7 11z"
            stroke="currentColor"
            strokeWidth="1.6"
          />
          <circle cx="12" cy="10" r="2.6" stroke="currentColor" strokeWidth="1.6" />
        </svg>
        <input
          value={raw}
          onChange={(e) => {
            setRaw(e.target.value);
            setError(null);
          }}
          onKeyDown={(e) => e.key === "Enter" && !submitting && submit()}
          placeholder="Paste coordinates — e.g. 42.9000, -74.3000 — or click the map"
          className="h-10 flex-1 bg-transparent text-sm text-zinc-100 placeholder:text-zinc-600 focus:outline-none"
          spellCheck={false}
        />
        <Button onClick={submit} disabled={submitting} className="shrink-0">
          {submitting ? (
            <>
              <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-[#06251A]/30 border-t-[#06251A]" />
              Starting…
            </>
          ) : (
            "Analyze Site"
          )}
        </Button>
      </div>

      <div className="flex items-center justify-between pt-2.5">
        <AnimatePresence mode="wait">
          {error ? (
            <motion.p
              key="err"
              initial={{ opacity: 0, y: -4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              className="text-xs text-danger"
            >
              {error}
            </motion.p>
          ) : (
            <motion.p key="hint" initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="text-xs text-zinc-600">
              WGS 84 decimal degrees · blank acreage assumes 300 ac · runs in ~20 seconds
            </motion.p>
          )}
        </AnimatePresence>
        <button
          onClick={() => {
            setRaw(DEMO_COORDS);
            setError(null);
          }}
          className="shrink-0 whitespace-nowrap text-xs text-accent/80 transition-colors hover:text-accent"
        >
          Try demo site ↗
        </button>
      </div>
    </div>
  );
}
