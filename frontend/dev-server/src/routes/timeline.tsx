import { createFileRoute } from "@tanstack/react-router";
import { AppShell } from "@/components/AppShell";

export const Route = createFileRoute("/timeline")({
  head: () => ({
    meta: [
      { title: "Clinical Timeline · Anustan" },
      {
        name: "description",
        content:
          "A chronological clinical timeline built from intake conversations and extracted medical documents.",
      },
      { property: "og:title", content: "Clinical Timeline · Anustan" },
      {
        property: "og:description",
        content: "Every visit, medication and lab result in one chronological patient story.",
      },
    ],
  }),
  component: Timeline,
});

const EVENTS = [
  {
    date: "Today · 09:14",
    dot: "bg-brand",
    title: "AI intake completed",
    body: "Fever 3 days, chills, dry cough · 6 questions, हिन्दी voice",
  },
  {
    date: "Today · 08:40",
    dot: "bg-mint",
    title: "CBC report scanned",
    body: "WBC 11.4 ×10³/µL · CRP 18 mg/L (mild ↑)",
  },
  {
    date: "24 Jun 2026",
    dot: "bg-peach",
    title: "Prescription extracted",
    body: "Azithromycin 500 mg OD × 5 days · Dr. M. Rao",
  },
  {
    date: "15 Mar 2026",
    dot: "bg-rose",
    title: "Discharge summary",
    body: "Acute gastroenteritis · 3-day admission, IV fluids",
  },
  {
    date: "2023",
    dot: "bg-ink-soft",
    title: "Allergy recorded",
    body: "Sulfa drugs — rash",
  },
];

function Timeline() {
  return (
    <AppShell>
      <section className="animate-rise rounded-[28px] bg-glass-soft p-5 shadow-card ring-1 ring-white/70">
        <p className="text-[11px] font-extrabold tracking-[0.18em] text-brand uppercase">
          Longitudinal record
        </p>
        <h1 className="mt-1 font-display text-[26px] leading-tight font-bold">Clinical timeline</h1>
        <p className="mt-1 text-[13px] font-semibold text-ink-soft">
          Conversations and documents merged into one story.
        </p>
      </section>

      <section className="rounded-3xl bg-glass-soft p-5 ring-1 ring-white/70">
        <div className="border-l-2 border-brand/20 pl-5">
          {EVENTS.map((e, i) => (
            <div
              key={e.title}
              className="animate-rise relative pb-5 last:pb-0"
              style={{ animationDelay: `${i * 80}ms` }}
            >
              <span
                className={"absolute -left-[26px] top-1 size-3 rounded-full ring-4 ring-white/70 " + e.dot}
              />
              <p className="text-[10px] font-bold tracking-wide text-ink-soft uppercase">{e.date}</p>
              <p className="font-display text-[14px] font-bold text-ink">{e.title}</p>
              <p className="mt-0.5 text-[12px] font-semibold text-ink-soft">{e.body}</p>
            </div>
          ))}
        </div>
      </section>
    </AppShell>
  );
}
