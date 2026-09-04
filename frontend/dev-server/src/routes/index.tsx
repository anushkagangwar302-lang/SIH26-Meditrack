import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { AppShell } from "@/components/AppShell";
import { Waveform } from "@/components/Waveform";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Anustan · AI Patient Intake Kiosk" },
      {
        name: "description",
        content:
          "Multilingual voice and touchscreen patient history-taking with adaptive follow-up questions.",
      },
      { property: "og:title", content: "Anustan · AI Patient Intake Kiosk" },
      {
        property: "og:description",
        content:
          "Multilingual voice and touchscreen patient history-taking with adaptive follow-up questions.",
      },
    ],
  }),
  component: Intake,
});

const QUESTIONS = [
  {
    tag: "Step 2 of 6 · Fever",
    text: "Sneha, how long has the fever been going on?",
    options: ["Under 24 hrs", "1–3 days", "Over a week"],
  },
  {
    tag: "Step 3 of 6 · Fever",
    text: "Does the fever come and go, or stay all day?",
    options: ["Comes and goes", "Stays all day", "Only at night"],
  },
  {
    tag: "Step 4 of 6 · Associated",
    text: "Any chills, body ache or sweating with it?",
    options: ["Chills", "Body ache", "Sweating", "None"],
  },
];

function Intake() {
  const [step, setStep] = useState(0);
  const [picked, setPicked] = useState<string | null>(null);
  const [listening, setListening] = useState(true);
  const q = QUESTIONS[step] ?? QUESTIONS[0]!;

  const answer = (opt: string) => {
    setPicked(opt);
    setTimeout(() => {
      setPicked(null);
      setStep((s) => (s + 1) % QUESTIONS.length);
    }, 450);
  };

  return (
    <AppShell>
      <section
        key={step}
        className="animate-rise rounded-[28px] bg-glass-soft p-5 shadow-card ring-1 ring-white/70"
      >
        <p className="text-[11px] font-extrabold tracking-[0.18em] text-brand uppercase">{q.tag}</p>
        <h1 className="mt-1 font-display text-[26px] leading-tight font-bold">{q.text}</h1>
        <p className="mt-1 text-[13px] font-semibold text-ink-soft">
          Tap to answer, or speak freely — I'll follow up.
        </p>

        <div className="mt-4 flex items-center gap-4 rounded-3xl bg-gradient-to-br from-brand/15 to-mint/20 p-4 ring-1 ring-white/70">
          <button
            onClick={() => setListening((l) => !l)}
            aria-label={listening ? "Stop recording" : "Start recording"}
            className="grid size-14 shrink-0 place-items-center rounded-full bg-brand text-brand-foreground shadow-glow"
          >
            <span
              className={
                listening ? "block size-5 rounded-sm bg-brand-foreground" : "block size-5 rounded-full bg-brand-foreground"
              }
            />
          </button>
          <Waveform active={listening} />
        </div>

        <div className="mt-3 flex flex-wrap gap-2">
          {q.options.map((opt) => (
            <button
              key={opt}
              onClick={() => answer(opt)}
              className={
                "rounded-full px-3.5 py-2 text-[12px] font-bold text-ink ring-1 " +
                (picked === opt
                  ? "bg-mint/30 ring-mint/50"
                  : "bg-white/80 ring-white/80")
              }
            >
              {opt}
            </button>
          ))}
        </div>
      </section>

      <section className="rounded-3xl bg-glass-soft p-4 shadow-card ring-1 ring-white/70">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="grid size-9 place-items-center rounded-xl bg-peach/30">
              <span className="text-base">📄</span>
            </div>
            <div>
              <p className="font-display text-[13px] font-bold">Scan a lab report</p>
              <p className="text-[11px] font-semibold text-ink-soft">OCR + AI entity extraction</p>
            </div>
          </div>
          <span className="rounded-full bg-mint/25 px-2.5 py-1 text-[10px] font-extrabold text-ink">
            98% match
          </span>
        </div>
        <div className="mt-3 grid grid-cols-2 gap-2">
          {[
            { k: "WBC count", v: "11.4", u: "×10³/µL" },
            { k: "Hemoglobin", v: "12.1", u: "g/dL" },
          ].map((m) => (
            <div key={m.k} className="rounded-2xl bg-white/70 p-3 ring-1 ring-white/80">
              <p className="text-[10px] font-bold tracking-wide text-ink-soft uppercase">{m.k}</p>
              <p className="text-[17px] font-bold text-brand">
                {m.v} <span className="text-[11px] text-ink-soft">{m.u}</span>
              </p>
            </div>
          ))}
        </div>
      </section>

      <section className="rounded-3xl bg-glass-soft p-4 ring-1 ring-white/70">
        <p className="text-[11px] font-extrabold tracking-[0.18em] text-rose uppercase">
          Adaptive follow-up
        </p>
        <div className="mt-2 space-y-2">
          {[
            { c: "bg-brand", t: "Any throat pain or runny nose?" },
            { c: "bg-mint", t: "Are you on any regular medication?" },
          ].map((f) => (
            <div key={f.t} className="flex items-start gap-2">
              <span className={"mt-1 size-2 shrink-0 rounded-full " + f.c} />
              <p className="text-[13px] font-semibold text-ink">{f.t}</p>
            </div>
          ))}
        </div>
      </section>
    </AppShell>
  );
}
