import Link from "next/link";

export function Nav() {
  return (
    <header className="sticky top-0 z-[1000] border-b border-edge bg-base/80 backdrop-blur-md">
      <div className="mx-auto flex h-14 max-w-7xl items-center justify-between px-6">
        <Link href="/" className="flex items-center gap-2.5 group">
          <span className="relative flex h-7 w-7 items-center justify-center rounded-md bg-accent/15 transition-colors group-hover:bg-accent/25">
            {/* Shield-grid mark */}
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" className="text-accent">
              <path
                d="M12 2L4 5.5v6c0 4.6 3.4 8.9 8 10.5 4.6-1.6 8-5.9 8-10.5v-6L12 2z"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinejoin="round"
              />
              <path d="M8 11.5h8M12 7.5v8" stroke="currentColor" strokeWidth="1.4" />
            </svg>
          </span>
          <span className="text-[15px] font-semibold tracking-tight text-zinc-100">
            Grid<span className="text-accent">Sentry</span>
          </span>
        </Link>
        <nav className="flex items-center gap-1 text-sm">
          <Link
            href="/"
            className="rounded-md px-3 py-1.5 text-zinc-400 transition-colors hover:bg-white/5 hover:text-zinc-200"
          >
            Analyze
          </Link>
          <a
            href="https://www.epa.gov/nepa"
            target="_blank"
            rel="noreferrer"
            className="rounded-md px-3 py-1.5 text-zinc-400 transition-colors hover:bg-white/5 hover:text-zinc-200"
          >
            NEPA Reference
          </a>
          <span className="ml-3 hidden items-center gap-1.5 rounded-full border border-edge bg-surface px-3 py-1 text-[11px] text-zinc-500 sm:flex">
            <span className="h-1.5 w-1.5 rounded-full bg-accent animate-pulseDot" />
            Agents online
          </span>
        </nav>
      </div>
    </header>
  );
}
