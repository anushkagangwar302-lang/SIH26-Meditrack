import { Link, useRouterState } from "@tanstack/react-router";
import { useState, type ReactNode } from "react";

const LANGUAGES = ["English", "हिन्दी", "தமிழ்", "বাংলা", "मराठी"];

const NAV = [
  { to: "/", icon: "🎙️", label: "Talk" },
  { to: "/summary", icon: "📝", label: "Summary" },
  { to: "/documents", icon: "📄", label: "Documents" },
  { to: "/timeline", icon: "🕒", label: "Timeline" },
] as const;

export function AppShell({ children }: { children: ReactNode }) {
  const [lang, setLang] = useState(0);
  const pathname = useRouterState({ select: (s) => s.location.pathname });

  return (
    <div className="relative min-h-screen w-full overflow-hidden bg-app font-body text-ink">
      <div aria-hidden className="pointer-events-none absolute -top-10 -left-12 size-52 rounded-full bg-rose/30" />
      <div aria-hidden className="pointer-events-none absolute top-40 -right-16 size-60 rounded-full bg-mint/30" />
      <div aria-hidden className="pointer-events-none absolute bottom-10 left-6 size-40 rounded-full bg-peach/30" />

      <header className="relative z-10 flex items-center justify-between px-5 pt-5">
        <div className="flex items-center gap-2.5">
          <div className="grid size-9 place-items-center rounded-2xl bg-glass font-display shadow-glow ring-1 ring-white/80">
            <span className="text-base font-bold text-brand">A</span>
          </div>
          <div className="leading-tight">
            <p className="font-display text-[15px] font-bold">Anustan</p>
            <p className="text-[10px] font-semibold text-ink-soft">AI Patient Intake</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setLang((l) => (l + 1) % LANGUAGES.length)}
            className="flex items-center gap-1.5 rounded-full bg-glass px-2.5 py-1.5 text-[11px] font-bold text-ink ring-1 ring-white/80"
          >
            <span className="size-1.5 rounded-full bg-mint" /> {LANGUAGES[lang]}
          </button>
          <div className="grid size-9 place-items-center rounded-full bg-glass text-sm font-bold ring-1 ring-white/80">
            RU
          </div>
        </div>
      </header>

      <main className="relative z-10 space-y-4 px-4 pt-4 pb-28">{children}</main>

      <nav className="fixed inset-x-0 bottom-0 z-20">
        <div className="mx-auto mb-4 flex max-w-md items-center gap-1.5 rounded-[26px] bg-glass-strong p-2 shadow-float ring-1 ring-white/80 backdrop-blur-xl">
          {NAV.map((item) => {
            const active = pathname === item.to;
            return (
              <Link
                key={item.to}
                to={item.to}
                className={
                  "flex flex-1 flex-col items-center gap-1 rounded-2xl py-2 text-[10px] font-bold " +
                  (active
                    ? "bg-gradient-to-br from-brand to-brand-soft text-brand-foreground shadow-glow"
                    : "text-ink-soft")
                }
              >
                <span className="text-lg">{item.icon}</span> {item.label}
              </Link>
            );
          })}
        </div>
      </nav>
    </div>
  );
}
