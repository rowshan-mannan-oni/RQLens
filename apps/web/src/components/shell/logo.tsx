import Link from "next/link";

/** The RQ Lens mark: a lens over a small bar chart. */
export function LogoMark({ className = "h-7 w-7" }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" aria-hidden className={className}>
      <rect width="32" height="32" rx="8" className="fill-brand" />
      <rect
        x="8"
        y="16"
        width="3"
        height="6"
        rx="1"
        fill="white"
        opacity="0.7"
      />
      <rect
        x="12.5"
        y="12"
        width="3"
        height="10"
        rx="1"
        fill="white"
        opacity="0.85"
      />
      <rect x="17" y="9" width="3" height="13" rx="1" fill="white" />
      <circle
        cx="19.5"
        cy="14.5"
        r="6"
        fill="none"
        stroke="white"
        strokeWidth="2"
      />
      <path
        d="M23.8 18.8 26 21"
        stroke="white"
        strokeWidth="2.2"
        strokeLinecap="round"
      />
    </svg>
  );
}

export function Logo({ href = "/projects" }: { href?: string }) {
  return (
    <Link href={href} className="flex items-center gap-2 rounded-md">
      <LogoMark />
      <span className="text-[15px] font-semibold tracking-tight">RQ Lens</span>
    </Link>
  );
}
