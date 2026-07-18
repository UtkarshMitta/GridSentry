"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { CoordinateInput } from "@/components/coordinate-input";
import { SiteMap } from "@/components/site-map";
import { Badge, Card } from "@/components/ui";

const FEATURES = [
  {
    title: "Geolocation Analyst",
    body: "Cross-references USFWS wetlands, critical habitat, PAD-US protected areas, and FEMA flood layers around your coordinates.",
  },
  {
    title: "Legal Compliance Officer",
    body: "Maps every spatial finding to the controlling regulation — NEPA, CWA § 404, ESA § 7, and state wetland statutes — with pinpoint citations.",
  },
  {
    title: "Red-Team Critic",
    body: "Adversarially challenges the draft: weak citations, survey gaps, and stop-work risks surface before your reviewers find them.",
  },
];

export default function Home() {
  const [picked, setPicked] = useState<{ lat: number; lon: number } | null>(null);

  return (
    <div className="mx-auto max-w-7xl px-6">
      {/* Hero */}
      <section className="grid items-center gap-10 py-14 lg:grid-cols-[1.05fr_1fr] lg:py-20">
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, ease: "easeOut" }}
        >
          <Badge tone="accent" className="mb-5">
            <span className="h-1.5 w-1.5 rounded-full bg-accent" />
            Autonomous NEPA permit agent
          </Badge>
          <h1 className="max-w-xl text-4xl font-bold leading-[1.1] tracking-tight text-zinc-50 sm:text-5xl">
            Environmental review,{" "}
            <span className="text-accent">before you break ground.</span>
          </h1>
          <p className="mt-5 max-w-lg text-base leading-relaxed text-zinc-400">
            Drop coordinates for any solar, wind, or transmission site. Three
            specialized agents cross-reference federal environmental databases
            and draft a fully cited impact assessment in about twenty seconds.
          </p>
          <div className="mt-8">
            <CoordinateInput picked={picked} />
          </div>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, scale: 0.97 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.6, ease: "easeOut", delay: 0.15 }}
        >
          <Card className="overflow-hidden">
            <div className="flex items-center justify-between border-b border-edge px-4 py-2.5">
              <span className="text-xs font-medium text-zinc-400">
                Live site preview
              </span>
              <span className="text-[11px] text-zinc-600">
                Click anywhere to select a site
              </span>
            </div>
            <div className="h-[420px]">
              <SiteMap
                center={[42.9000, -74.3000]}
                zoom={9}
                marker={picked ? [picked.lat, picked.lon] : null}
                onPick={(lat, lon) => setPicked({ lat, lon })}
              />
            </div>
          </Card>
        </motion.div>
      </section>

      {/* Agent trio */}
      <section className="pb-20">
        <div className="grid gap-4 md:grid-cols-3">
          {FEATURES.map((f, i) => (
            <motion.div
              key={f.title}
              initial={{ opacity: 0, y: 20 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: "-60px" }}
              transition={{ duration: 0.45, delay: i * 0.08 }}
            >
              <Card className="h-full p-5 transition-colors duration-200 hover:border-accent/30">
                <div className="mb-3 flex h-8 w-8 items-center justify-center rounded-lg bg-accent/10 text-sm font-semibold text-accent">
                  {i + 1}
                </div>
                <h3 className="text-sm font-semibold text-zinc-100">{f.title}</h3>
                <p className="mt-2 text-[13px] leading-relaxed text-zinc-500">
                  {f.body}
                </p>
              </Card>
            </motion.div>
          ))}
        </div>
      </section>
    </div>
  );
}
