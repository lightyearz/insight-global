import Link from "next/link";

export default function NotFound() {
  return (
    <div className="flex flex-col items-start gap-2">
      <h1 className="text-xl font-semibold text-ink">Page not found</h1>
      <Link href="/" className="text-sm font-medium text-accent underline">
        Back to briefings
      </Link>
    </div>
  );
}
