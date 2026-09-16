"use client";

import { MotionConfig } from "framer-motion";

/**
 * Honour the OS "reduce motion" setting: transitions become instant instead of
 * animating (content never depends on an animation having run to be visible).
 */
export function Providers({ children }: { children: React.ReactNode }) {
  return <MotionConfig reducedMotion="user">{children}</MotionConfig>;
}
