import { Plus } from "lucide-react";
import { BriefingsTable } from "@/components/BriefingsTable";
import { ButtonLink } from "@/components/ui";

export default function DashboardPage() {
  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-ink">Briefings</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted">
            Standard-of-care briefings built from public guidelines, systematic reviews and MedlinePlus. Each one is
            reviewed by a person before the report is written.
          </p>
        </div>
        <ButtonLink href="/briefings/new" variant="primary">
          <Plus aria-hidden="true" className="size-4" />
          New briefing
        </ButtonLink>
      </div>
      <BriefingsTable />
    </div>
  );
}
