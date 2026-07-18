export function Footer() {
  return (
    <footer className="border-t border-edge py-6">
      <div className="mx-auto flex max-w-7xl flex-col items-center justify-between gap-2 px-6 text-xs text-zinc-600 sm:flex-row">
        <span>© {new Date().getFullYear()} GridSentry, Inc.</span>
        <span className="font-medium uppercase tracking-[0.18em] text-zinc-600">
          Confidential — Demo Build
        </span>
        <span>Not legal advice. Assessments are AI-generated drafts.</span>
      </div>
    </footer>
  );
}
