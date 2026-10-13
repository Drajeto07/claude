/**
 * SmartDoc's mark and wordmark (original artwork): a page with a folded corner and a spark,
 * in the blue-to-purple brand gradient. `tone="light"` is for dark or coloured backgrounds.
 */
export function LogoMark({ className = "h-8 w-8" }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden="true" focusable="false">
      <defs>
        <linearGradient id="smartdoc-mark" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#2563eb" />
          <stop offset="1" stopColor="#7c3aed" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="9" fill="url(#smartdoc-mark)" />
      <path d="M10 8.5h8.5l4.5 4.5v10.5a1.5 1.5 0 0 1-1.5 1.5h-11.5a1.5 1.5 0 0 1-1.5-1.5v-13.5a1.5 1.5 0 0 1 1.5-1.5Z" fill="#fff" fillOpacity="0.95" />
      <path d="M18.5 8.5v3a1.5 1.5 0 0 0 1.5 1.5h3" fill="none" stroke="#c7d2fe" strokeWidth="1.2" />
      <path d="M12 17h7M12 20h5" stroke="#6366f1" strokeWidth="1.4" strokeLinecap="round" />
      <path d="M22.5 18.5l.7 1.6 1.6.7-1.6.7-.7 1.6-.7-1.6-1.6-.7 1.6-.7z" fill="#7c3aed" />
    </svg>
  );
}

export function Logo({ tone = "dark", className = "" }: { tone?: "dark" | "light"; className?: string }) {
  return (
    <span className={`inline-flex items-center gap-2.5 ${className}`}>
      {/* On the brand gradient the mark's own gradient would vanish: a light ring sets it off. */}
      <LogoMark className={tone === "light" ? "h-8 w-8 rounded-[9px] shadow-md ring-2 ring-white/50" : "h-8 w-8"} />
      <span className={`text-lg font-semibold tracking-tight ${tone === "light" ? "text-white" : "text-foreground"}`}>SmartDoc</span>
    </span>
  );
}
