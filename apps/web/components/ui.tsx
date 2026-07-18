import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import type { ButtonHTMLAttributes, HTMLAttributes } from "react";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "ghost" | "outline";
  size?: "sm" | "md" | "lg";
};

export function Button({
  className,
  variant = "primary",
  size = "md",
  ...props
}: ButtonProps) {
  return (
    <button
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-lg font-medium transition-all duration-150",
        "focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent/60",
        "disabled:pointer-events-none disabled:opacity-50",
        variant === "primary" &&
          "bg-accent text-[#06251A] shadow-glow hover:bg-[#40D69C] active:scale-[0.98]",
        variant === "ghost" && "text-zinc-400 hover:bg-white/5 hover:text-zinc-200",
        variant === "outline" &&
          "border border-edge bg-surface text-zinc-300 hover:border-accent/40 hover:text-zinc-100",
        size === "sm" && "h-8 px-3 text-xs",
        size === "md" && "h-10 px-4 text-sm",
        size === "lg" && "h-12 px-6 text-base",
        className,
      )}
      {...props}
    />
  );
}

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "rounded-xl border border-edge bg-surface shadow-card",
        className,
      )}
      {...props}
    />
  );
}

type BadgeProps = HTMLAttributes<HTMLSpanElement> & {
  tone?: "accent" | "danger" | "amber" | "neutral";
};

export function Badge({ className, tone = "neutral", ...props }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[11px] font-medium tracking-wide",
        tone === "accent" && "bg-accent/15 text-accent",
        tone === "danger" && "bg-danger/15 text-danger",
        tone === "amber" && "bg-amber/15 text-amber",
        tone === "neutral" && "bg-white/[0.06] text-zinc-400",
        className,
      )}
      {...props}
    />
  );
}

export function Skeleton({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("skeleton", className)} {...props} />;
}

export function riskTone(risk: string): "accent" | "danger" | "amber" | "neutral" {
  if (risk === "high") return "danger";
  if (risk === "moderate") return "amber";
  if (risk === "low") return "accent";
  return "neutral";
}
