import { Inbox } from "lucide-react";
import Link from "next/link";

export function EmptyState({
  title,
  text,
  href,
  action,
}: {
  title: string;
  text: string;
  href?: string;
  action?: string;
}) {
  return (
    <div className="card flex flex-col items-center gap-2 px-6 py-10 text-center">
      <span className="bg-surface-3 text-subtle grid h-10 w-10 place-items-center rounded-full">
        <Inbox className="h-5 w-5" aria-hidden />
      </span>
      <p className="font-medium">{title}</p>
      <p className="text-muted max-w-sm text-sm">{text}</p>
      {href && action && (
        <Link href={href} className="btn btn-secondary btn-sm mt-2">
          {action}
        </Link>
      )}
    </div>
  );
}
