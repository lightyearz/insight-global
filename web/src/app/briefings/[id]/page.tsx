import type { Metadata } from "next";
import { BriefingDetail } from "@/components/BriefingDetail";

export const metadata: Metadata = { title: "Briefing" };

export default async function BriefingPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <BriefingDetail id={id} />;
}
