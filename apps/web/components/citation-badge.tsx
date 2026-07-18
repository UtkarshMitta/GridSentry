"use client";

import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import type { Citation } from "@/lib/types";

export function CitationBadge({ citation }: { citation: Citation }) {
  const [open, setOpen] = useState(false);

  return (
    <span
      className="relative inline-block"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <a
        href={citation.url}
        target="_blank"
        rel="noreferrer"
        className="inline-flex items-center gap-1 rounded-md border border-accent/25 bg-accent/[0.08] px-1.5 py-0.5 font-mono text-[10.5px] font-medium text-accent transition-colors hover:border-accent/50 hover:bg-accent/15"
      >
        {citation.label}
        <svg width="9" height="9" viewBox="0 0 12 12" fill="none" className="opacity-60">
          <path d="M3.5 8.5l5-5M5 3h3.5V6.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
        </svg>
      </a>
      <AnimatePresence>
        {open && (
          <motion.span
            initial={{ opacity: 0, y: 4, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 4, scale: 0.97 }}
            transition={{ duration: 0.15 }}
            className="absolute bottom-full left-0 z-50 mb-2 block w-72 rounded-lg border border-edge bg-raised p-3 shadow-card"
          >
            <span className="block text-xs font-semibold text-zinc-100">
              {citation.title}
            </span>
            <span className="mt-1 block text-[11px] leading-relaxed text-zinc-400">
              {citation.excerpt}
            </span>
            <span className="mt-2 block text-[10px] uppercase tracking-wider text-zinc-600">
              {citation.source}
            </span>
          </motion.span>
        )}
      </AnimatePresence>
    </span>
  );
}
