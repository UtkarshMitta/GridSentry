import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        base: "#0B0F14",
        surface: "#11161D",
        raised: "#161D26",
        edge: "rgba(255,255,255,0.07)",
        accent: {
          DEFAULT: "#35C78F",
          dim: "#2AA377",
          glow: "rgba(53,199,143,0.15)",
        },
        danger: "#F0625D",
        amber: "#E8B25A",
      },
      fontFamily: {
        sans: ["var(--font-inter)", "system-ui", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      boxShadow: {
        card: "0 1px 0 rgba(255,255,255,0.04) inset, 0 8px 24px rgba(0,0,0,0.35)",
        glow: "0 0 32px rgba(53,199,143,0.18)",
      },
      keyframes: {
        shimmer: {
          "0%": { backgroundPosition: "-400px 0" },
          "100%": { backgroundPosition: "400px 0" },
        },
        pulseDot: {
          "0%, 100%": { opacity: "0.4", transform: "scale(0.9)" },
          "50%": { opacity: "1", transform: "scale(1.1)" },
        },
      },
      animation: {
        shimmer: "shimmer 1.6s linear infinite",
        pulseDot: "pulseDot 1.4s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};

export default config;
