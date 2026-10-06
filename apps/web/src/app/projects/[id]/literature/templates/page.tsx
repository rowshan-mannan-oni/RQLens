import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { redirect } from "next/navigation";

import { auth } from "@/auth";
import { TemplateEditor } from "@/components/literature/template-editor";
import { apiFetch } from "@/lib/api";
import type { ReviewTemplate } from "@/lib/types";

export default async function TemplatesPage(
  props: PageProps<"/projects/[id]/literature/templates">,
) {
  const session = await auth();
  if (!session?.user) redirect("/");
  const { id } = await props.params;
  const templates = await apiFetch<ReviewTemplate[]>("/templates");
  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-start gap-3">
        <Link
          href={`/projects/${id}/literature`}
          className="btn btn-ghost btn-sm mt-0.5"
          aria-label="Back to the literature review"
        >
          <ArrowLeft className="h-4 w-4" aria-hidden />
        </Link>
        <div>
          <h2 className="text-xl font-semibold tracking-tight">
            Review templates
          </h2>
          <p className="lead mt-1 max-w-3xl">
            A template is the set of columns of a literature table. Each column
            has plain-language instructions for the AI and a kind: text, a list,
            a number, or a category with fixed options. Your templates are
            available in all your projects.
          </p>
        </div>
      </div>
      <TemplateEditor projectId={Number(id)} templates={templates} />
    </div>
  );
}
