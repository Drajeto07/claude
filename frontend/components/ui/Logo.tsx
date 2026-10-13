/**
 * SmartDoc's mark and wordmark (original artwork): a page with a folded corner and a spark on
 * the blue-to-purple brand gradient. The gradient is CSS, not an SVG <linearGradient>: an id
 * repeated by every copy of the logo resolves to the first copy's, and when that copy is hidden
 * (the sidebar on a phone) the others lose their colour. `tone="light"` is for coloured backgrounds.
 */
export function LogoMark({ className = "h-8 w-8" }: { className?: string }) {
  return (
    <span aria-hidden="true" className={`inline-flex shrink-0 items-center justify-center rounded-[9px] bg-gradient-to-br from-brand-blue to-brand-purple ${className}`}>
      <svg viewBox="0 0 32 32" className="h-full w-full" focusable="false">
        <path d="M10 8.5h8.5l4.5 4.5v10.5a1.5 1.5 0 0 1-1.5 1.5h-11.5a1.5 1.5 0 0 1-1.5-1.5v-13.5a1.5 1.5 0 0 1 1.5-1.5Z" fill="#fff" fillOpacity="0.95" />
        <path d="M18.5 8.5v3a1.5 1.5 0 0 0 1.5 1.5h3" fill="none" stroke="#c7d2fe" strokeWidth="1.2" />
        <path d="M12 17h7M12 20h5" stroke="#6366f1" strokeWidth="1.4" strokeLinecap="round" />
        <path d="M22.5 18.5l.7 1.6 1.6.7-1.6.7-.7 1.6-.7-1.6-1.6-.7 1.6-.7z" fill="#7c3aed" />
      </svg>
    </span>
  );
}

export function Logo({ tone = "dark", className = "" }: { tone?: "dark" | "light"; className?: string }) {
  return (
    <span className={`inline-flex items-center gap-2.5 ${className}`}>
      {/* On the brand gradient the mark's own gradient would vanish: a light ring sets it off. */}
      <LogoMark className={tone === "light" ? "h-8 w-8 shadow-md ring-2 ring-white/50" : "h-8 w-8"} />
      <span className={`text-lg font-semibold tracking-tight ${tone === "light" ? "text-white" : "text-foreground"}`}>SmartDoc</span>
    </span>
  );
}
