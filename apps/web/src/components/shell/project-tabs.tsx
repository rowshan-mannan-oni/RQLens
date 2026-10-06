"use client";

import {
  BookOpenText,
  ChartNoAxesColumn,
  LayoutGrid,
  Lightbulb,
  MessagesSquare,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

type Tab = { href: string; label: string; icon: LucideIcon; match: RegExp };

export function ProjectTabs({ projectId }: { projectId: number }) {
  const pathname = usePathname();
  const base = `/projects/${projectId}`;
  const tabs: Tab[] = [
    {
      href: base,
      label: "Overview",
      icon: LayoutGrid,
      match: new RegExp(`^${base}(/datasets/.*|/compare.*)?$`),
    },
    {
      href: `${base}/rqs`,
      label: "Research questions",
      icon: ChartNoAxesColumn,
      match: new RegExp(`^${base}/rqs`),
    },
    {
      href: `${base}/insights`,
      label: "Insights",
      icon: Lightbulb,
      match: new RegExp(`^${base}/insights`),
    },
    {
      href: `${base}/literature`,
      label: "Literature",
      icon: BookOpenText,
      match: new RegExp(`^${base}/literature`),
    },
    {
      href: `${base}/chat`,
      label: "Chat",
      icon: MessagesSquare,
      match: new RegExp(`^${base}/chat`),
    },
  ];
  return (
    <nav
      aria-label="Project sections"
      className="-mb-px flex [scrollbar-width:none] gap-1 overflow-x-auto"
    >
      {tabs.map(({ href, label, icon: Icon, match }) => {
        const active = match.test(pathname);
        return (
          <Link
            key={href}
            href={href}
            aria-current={active ? "page" : undefined}
            className="group text-muted hover:text-fg aria-[current=page]:border-brand aria-[current=page]:text-fg flex shrink-0 items-center gap-2 border-b-2 border-transparent px-3 py-2.5 text-sm font-medium transition-colors"
          >
            <Icon
              className="text-subtle group-hover:text-muted group-aria-[current=page]:text-brand h-4 w-4"
              aria-hidden
            />
            {label}
          </Link>
        );
      })}
    </nav>
  );
}
