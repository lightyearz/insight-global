import type { Metadata } from "next";
import { NewBriefingForm } from "@/components/NewBriefingForm";

export const metadata: Metadata = { title: "New briefing" };

export default function NewBriefingPage() {
  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-5">
      <div>
        <h1 className="text-xl font-semibold text-ink">New briefing</h1>
        <p className="mt-1 text-sm text-muted">
          The standard-of-care agent searches PubMed guidelines and systematic reviews plus MedlinePlus, extracts the
          current treatment options with quotes, and then pauses for your review.
        </p>
      </div>
      <NewBriefingForm />
    </div>
  );
}
