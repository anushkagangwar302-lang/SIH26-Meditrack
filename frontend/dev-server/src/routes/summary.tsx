import { createFileRoute } from "@tanstack/react-router";
import { AppShell } from "@/components/AppShell";

export const Route = createFileRoute("/summary")({
  head: () => ({
    meta: [
      { title: "Physician Summary · Anustan" },
      {
        name: "description",
        content:
          "Structured, physician-ready clinical summary generated from the patient's AI intake conversation.",
      },
      { property: "og:title", content: "Physician Summary · Anustan" },
      {
        property: "og:description",
        content: "Structured clinical summary with vitals, HPI, medications and allergies.",
      },
    ],
  }),
  component: Summary,
});

const VITALS = [
  { k: "Temp", v: "101.2", u: "°F", flag: true },
  { k: "BP", v: "118/76", u: "mmHg", flag: false },
  { k: "HR", v: "98", u: "bpm", flag: false },
  { k: "SpO₂", v: "97", u: "%", flag: false },
];

const SECTIONS = [
  {
    title: "Chief complaint",
    accent: "bg-brand",
    lines: ["Fever with chills — 3 days", "Reported in हिन्दी, auto-translated"],
  },
  {
    title: "History of present illness",
    accent: "bg-mint",
    lines: [
      "Intermittent fever, peaks in the evening",
      "Associated body ache, mild dry cough",
      "No breathlessness, no urinary symptoms",
    ],
  },
  {
    title: "Medications",
    accent: "bg-peach",
    lines: ["Paracetamol 650 mg · TDS × 3 days", "Metformin 500 mg · OD (ongoing)"],
  },
  {
    title: "Allergies",
    accent: "bg-rose",
    lines: ["Sulfa drugs — rash (documented 2023)"],
  },
];

function Summary() {
  return (
    <AppShell>
      <section className="animate-rise rounded-[28px] bg-glass-soft p-5 shadow-card ring-1 ring-white/70">
        <p className="text-[11px] font-extrabold tracking-[0.18em] text-brand uppercase">
          Physician-ready summary
        </p>
        <h1 className="mt-1 font-display text-[26px] leading-tight font-bold">Sneha R. · 34 F</h1>
        <p className="mt-1 text-[13px] font-semibold text-ink-soft">
          Generated in 4 min 12 s · OPD 3 · Reviewed by AI, not diagnostic
        </p>

        <div className="mt-4 grid grid-cols-4 gap-2">
          {VITALS.map((v) => (
            <div key={v.k} className="rounded-2xl bg-white/70 p-2 text-center ring-1 ring-white/80">
              <p className={"text-[15px] font-bold " + (v.flag ? "text-rose" : "text-brand")}>
                {v.v}
              </p>
              <p className="mt-0.5 text-[9px] font-bold tracking-wide text-ink-soft uppercase">
                {v.k}
              </p>
            </div>
          ))}
        </div>
      </section>

      {SECTIONS.map((s) => (
        <section key={s.title} className="rounded-3xl bg-glass-soft p-4 ring-1 ring-white/70">
          <p className="text-[11px] font-extrabold tracking-[0.18em] text-ink-soft uppercase">
            {s.title}
          </p>
          <div className="mt-2 space-y-2">
            {s.lines.map((l) => (
              <div key={l} className="flex items-start gap-2">
                <span className={"mt-1 size-2 shrink-0 rounded-full " + s.accent} />
                <p className="text-[13px] font-semibold text-ink">{l}</p>
              </div>
            ))}
          </div>
        </section>
      ))}

      <button className="w-full rounded-3xl bg-gradient-to-br from-brand to-brand-soft py-4 font-display text-[15px] font-bold text-brand-foreground shadow-glow">
        Send to consulting physician
      </button>
    </AppShell>
  );
}
