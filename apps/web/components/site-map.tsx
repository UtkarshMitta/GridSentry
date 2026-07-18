"use client";

import dynamic from "next/dynamic";
import { Skeleton } from "./ui";
import type { SiteMapProps } from "./site-map-inner";

// Leaflet touches `window` — must render client-side only.
const SiteMapInner = dynamic(() => import("./site-map-inner"), {
  ssr: false,
  loading: () => <Skeleton className="h-full w-full rounded-none" />,
});

export function SiteMap(props: SiteMapProps) {
  return <SiteMapInner {...props} />;
}
