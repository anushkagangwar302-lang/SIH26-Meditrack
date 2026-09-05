import { createFileRoute, Link } from "@tanstack/react-router";
import { toast } from "sonner";
import { LanguageToggle, useI18n } from "@/lib/i18n";
import { Button } from "@/components/ui/button";

export const Route = createFileRoute("/emergency")({
  head: () => ({
    meta: [
      { title: "Emergency red flags · Anustan" },
      {
        name: "description",
        content:
          "Red flag symptoms that need immediate medical care, in English and Hindi, from Anustan AI patient intake.",
      },
      { property: "og:title", content: "Emergency red flags · Anustan" },
      {
        property: "og:description",
        content: "Red flag symptoms that need immediate medical care, in English and Hindi.",
      },
    ],
  }),
  component: EmergencyPage,
});

function EmergencyPage() {
  const { t } = useI18n();

  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-lg flex-col gap-5 px-4 py-6">
      <header className="flex items-center justify-between gap-3">
        <Link to="/" className="text-sm font-semibold text-primary">
          ← {t.back}
        </Link>
        <LanguageToggle />
      </header>

      <section className="card-soft p-6">
        <p className="kicker text-alert">{t.emergencyKicker}</p>
        <h1 className="mt-2 text-3xl font-bold leading-tight">{t.emergencyTitle}</h1>
        <p className="mt-2 text-base text-muted-foreground">{t.emergencySub}</p>
        <a
          href="tel:112"
          className="mt-5 flex h-14 items-center justify-center rounded-full bg-alert font-display text-base font-bold text-alert-foreground shadow-lift"
        >
          {t.callNow} · 112
        </a>
      </section>

      <section className="space-y-3">
        {t.flags.map((flag) => (
          <article key={flag.t} className="card-soft flex gap-3 p-5">
            <span className="mt-1.5 size-2.5 shrink-0 rounded-full bg-alert" />
            <div>
              <h2 className="font-display text-lg font-bold leading-snug">{flag.t}</h2>
              <p className="mt-1 text-sm text-muted-foreground">{flag.d}</p>
            </div>
          </article>
        ))}
      </section>

      <Button
        className="h-14 w-full rounded-full text-base font-bold shadow-lift"
        onClick={() => toast.success(t.escalated)}
      >
        {t.escalate}
      </Button>

      <p className="pb-4 text-center text-xs text-muted-foreground">{t.disclaimer}</p>
    </main>
  );
}
