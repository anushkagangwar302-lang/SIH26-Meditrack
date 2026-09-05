import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { AppShell } from "@/components/AppShell";

export const Route = createFileRoute("/documents")({
  head: () => ({
    meta: [
      { title: "Document Scanning & OCR · Anustan" },
      {
        name: "description",
        content:
          "Scan prescriptions, lab reports and discharge summaries — multilingual OCR extracts clinical entities automatically.",
      },
      { property: "og:title", content: "Document Scanning & OCR · Anustan" },
      {
        property: "og:description",
        content: "Multilingual OCR turns paper records into structured clinical entities.",
      },
    ],
  }),
  component: Documents,
});

const DOCS = [
  {
    icon: "💊",
    tint: "bg-peach/30",
    name: "Prescription · Dr. M. Rao",
    meta: "Handwritten · Hindi + English",
    confidence: "96%",
    fields: [
      { k: "Drug", v: "Azithromycin 500 mg" },
      { k: "Dose", v: "1 tab · OD × 5 d" },
      { k: "Advice", v: "Rest, oral fluids" },
      { k: "Flag", v: "Sulfa allergy", warn: true },
    ],
  },
  {
    icon: "🧪",
    tint: "bg-mint/30",
    name: "Lab report · CBC",
    meta: "Printed · 24 Jun 2026",
    confidence: "99%",
    fields: [
      { k: "WBC", v: "11.4 ×10³/µL" },
      { k: "Hb", v: "12.1 g/dL" },
      { k: "Platelets", v: "1.9 lakh/µL" },
      { k: "CRP", v: "18 mg/L ↑", warn: true },
    ],
  },
  {
    icon: "🏥",
    tint: "bg-rose/30",
    name: "Discharge summary",
    meta: "3 pages · Bengali",
    confidence: "92%",
    fields: [
      { k: "Admitted", v: "12–15 Mar 2026" },
      { k: "Diagnosis", v: "Acute gastroenteritis" },
      { k: "Procedure", v: "IV fluids, no surgery" },
      { k: "Follow-up", v: "Completed" },
    ],
  },
];

function Documents() {
  const [open, setOpen] = useState(0);

  return (
    <AppShell>
      <section className="animate-rise rounded-[28px] bg-glass-soft p-5 shadow-card ring-1 ring-white/70">
        <p className="text-[11px] font-extrabold tracking-[0.18em] text-brand uppercase">
          Document AI
        </p>
        <h1 className="mt-1 font-display text-[26px] leading-tight font-bold">
          Scan any medical paper
        </h1>
        <p className="mt-1 text-[13px] font-semibold text-ink-soft">
          Multilingual OCR → clinical entity extraction → timeline.
        </p>
        <button className="mt-4 flex w-full items-center justify-center gap-2 rounded-3xl bg-gradient-to-br from-brand to-brand-soft py-4 font-display text-[15px] font-bold text-brand-foreground shadow-glow">
          <span className="text-lg">📷</span> Open camera
        </button>
      </section>

      {DOCS.map((d, i) => (
        <section key={d.name} className="rounded-3xl bg-glass-soft p-4 ring-1 ring-white/70">
          <button
            onClick={() => setOpen(i === open ? -1 : i)}
            className="flex w-full items-center justify-between text-left"
          >
            <div className="flex items-center gap-2.5">
              <div className={"grid size-9 place-items-center rounded-xl " + d.tint}>
                <span className="text-base">{d.icon}</span>
              </div>
              <div>
                <p className="font-display text-[13px] font-bold">{d.name}</p>
                <p className="text-[11px] font-semibold text-ink-soft">{d.meta}</p>
              </div>
            </div>
            <span className="rounded-full bg-mint/25 px-2.5 py-1 text-[10px] font-extrabold text-ink">
              {d.confidence}
            </span>
          </button>

          {open === i && (
            <div className="mt-3 grid grid-cols-2 gap-2">
              {d.fields.map((f, fi) => (
                <div
                  key={f.k}
                  className="animate-rise rounded-2xl bg-white/70 p-3 ring-1 ring-white/80"
                  style={{ animationDelay: `${fi * 70}ms` }}
                >
                  <p className="text-[10px] font-bold tracking-wide text-ink-soft uppercase">
                    {f.k}
                  </p>
                  <p
                    className={
                      "text-[13px] font-bold " +
                      ("warn" in f && f.warn ? "text-rose" : "text-brand")
                    }
                  >
                    {f.v}
                  </p>
                </div>
              ))}
            </div>
          )}
        </section>
      ))}
    </AppShell>
  );
}
