import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { z } from "zod";
import { toast } from "sonner";
import { supabase } from "@/integrations/supabase/client";
import { lovable } from "@/integrations/lovable/index";
import { LanguageToggle, useI18n } from "@/lib/i18n";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Sign in · Anustan AI Patient Intake" },
      {
        name: "description",
        content:
          "Secure multilingual sign-in for Anustan AI patient intake — available in English and Hindi.",
      },
      { property: "og:title", content: "Sign in · Anustan AI Patient Intake" },
      {
        property: "og:description",
        content: "Secure multilingual sign-in for Anustan AI patient intake.",
      },
    ],
  }),
  component: SignInPage,
});

const schema = z.object({
  email: z.string().trim().email().max(255),
  password: z.string().min(6).max(72),
});

type Method = "email" | "abha" | "aadhaar";

const digits = (v: string) => v.replace(/\D/g, "");

function resolveIdentifier(method: Method, raw: string): { email: string } | { error: "abha" | "aadhaar" } {
  const value = raw.trim().toLowerCase();
  if (method === "abha") {
    const num = digits(value);
    if (num.length === 14) return { email: `abha-${num}@anustan.health` };
    if (/^[a-z0-9._-]{3,40}@[a-z0-9.-]{2,30}$/.test(value))
      return { email: `abha-${value.replace(/[^a-z0-9]/g, "-")}@anustan.health` };
    return { error: "abha" };
  }
  const num = digits(value);
  if (num.length === 12) return { email: `aadhaar-${num}@anustan.health` };
  return { error: "aadhaar" };
}

function SignInPage() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [method, setMethod] = useState<Method>("email");
  const [email, setEmail] = useState("");
  const [healthId, setHealthId] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [sessionEmail, setSessionEmail] = useState<string | null>(null);

  useEffect(() => {
    const { data } = supabase.auth.onAuthStateChange((_e, session) => {
      setSessionEmail(session?.user.email ?? null);
    });
    supabase.auth.getSession().then(({ data: s }) => setSessionEmail(s.session?.user.email ?? null));
    return () => data.subscription.unsubscribe();
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    let loginEmail = email;
    if (method !== "email") {
      const resolved = resolveIdentifier(method, healthId);
      if ("error" in resolved) {
        toast.error(resolved.error === "abha" ? t.idInvalidAbha : t.idInvalidAadhaar);
        return;
      }
      loginEmail = resolved.email;
    }
    const parsed = schema.safeParse({ email: loginEmail, password });
    if (!parsed.success) {
      toast.error(parsed.error.issues[0]?.message ?? "Invalid input");
      return;
    }
    setBusy(true);
    try {
      if (mode === "signup") {
        const { data, error } = await supabase.auth.signUp({
          email: parsed.data.email,
          password: parsed.data.password,
          options: { emailRedirectTo: window.location.origin },
        });
        if (error) throw error;
        if (!data.session && method === "email") toast.success(t.checkEmail);
        else if (data.session) toast.success(t.signedIn);
      } else {
        const { error } = await supabase.auth.signInWithPassword(parsed.data);
        if (error) throw error;
        toast.success(t.signedIn);
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  async function handleGoogle() {
    setBusy(true);
    const result = await lovable.auth.signInWithOAuth("google", {
      redirect_uri: window.location.origin,
    });
    if (result.error) {
      setBusy(false);
      toast.error(result.error.message ?? "Google sign-in failed");
      return;
    }
    if (result.redirected) return;
    setBusy(false);
    toast.success(t.signedIn);
    navigate({ to: "/" });
  }

  async function handleSignOut() {
    await supabase.auth.signOut();
    toast.success(t.signOut);
  }

  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-lg flex-col gap-5 px-4 py-6">
      <header className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className="flex size-11 items-center justify-center rounded-full bg-card font-display text-lg font-bold text-primary shadow-soft">
            A
          </span>
          <div>
            <p className="font-display text-lg font-bold leading-none">{t.brand}</p>
            <p className="text-sm text-muted-foreground">{t.tagline}</p>
          </div>
        </div>
        <LanguageToggle />
      </header>

      <section className="card-soft p-6">
        <p className="kicker">{t.signInKicker}</p>
        <h1 className="mt-2 text-3xl font-bold leading-tight">{t.signInTitle}</h1>
        <p className="mt-2 text-base text-muted-foreground">{t.signInSub}</p>

        {sessionEmail ? (
          <div className="mt-5 space-y-3">
            <p className="rounded-2xl bg-mint/50 px-4 py-3 text-sm font-semibold">{sessionEmail}</p>
            <Button variant="outline" className="w-full rounded-full" onClick={handleSignOut}>
              {t.signOut}
            </Button>
          </div>
        ) : (
          <form className="mt-5 space-y-4" onSubmit={handleSubmit}>
            <div className="flex gap-2 rounded-full bg-lilac/40 p-1">
              {(["email", "abha", "aadhaar"] as const).map((m) => (
                <button
                  key={m}
                  type="button"
                  onClick={() => setMethod(m)}
                  className={`flex-1 rounded-full px-3 py-2 text-sm font-semibold transition-colors ${
                    method === m ? "bg-card text-foreground shadow-soft" : "text-muted-foreground"
                  }`}
                >
                  {m === "email" ? t.methodEmail : m === "abha" ? t.methodAbha : t.methodAadhaar}
                </button>
              ))}
            </div>

            {method === "email" ? (
              <div className="space-y-1.5">
                <Label htmlFor="email">{t.email}</Label>
                <Input
                  id="email"
                  type="email"
                  autoComplete="email"
                  required
                  maxLength={255}
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="h-12 rounded-2xl border-0 bg-card shadow-soft"
                />
              </div>
            ) : (
              <div className="space-y-1.5">
                <Label htmlFor="healthId">
                  {method === "abha" ? t.abhaLabel : t.aadhaarLabel}
                </Label>
                <Input
                  id="healthId"
                  inputMode={method === "aadhaar" ? "numeric" : "text"}
                  autoComplete="off"
                  required
                  maxLength={60}
                  value={healthId}
                  onChange={(e) => setHealthId(e.target.value)}
                  placeholder={method === "abha" ? "12 3456 7890 1234" : "1234 5678 9012"}
                  className="h-12 rounded-2xl border-0 bg-card shadow-soft"
                />
                <p className="text-xs text-muted-foreground">
                  {method === "abha" ? t.abhaHelp : t.aadhaarHelp}
                </p>
              </div>
            )}
            <div className="space-y-1.5">
              <Label htmlFor="password">{t.password}</Label>
              <Input
                id="password"
                type="password"
                autoComplete={mode === "signup" ? "new-password" : "current-password"}
                required
                minLength={6}
                maxLength={72}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="h-12 rounded-2xl border-0 bg-card shadow-soft"
              />
            </div>
            <Button
              type="submit"
              disabled={busy}
              className="h-14 w-full rounded-full text-base font-bold shadow-lift"
            >
              {busy ? t.working : mode === "signup" ? t.signUp : t.signIn}
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={busy}
              onClick={handleGoogle}
              className="h-13 w-full rounded-full border-0 bg-card py-3 text-base font-semibold shadow-soft"
            >
              {t.google}
            </Button>
            <button
              type="button"
              className="w-full text-sm font-semibold text-primary"
              onClick={() => setMode(mode === "signup" ? "signin" : "signup")}
            >
              {mode === "signup" ? t.haveAccount : t.noAccount}
            </button>
            {method !== "email" && (
              <p className="rounded-2xl bg-blush/40 px-4 py-3 text-xs text-muted-foreground">
                {t.govNote}
              </p>
            )}
          </form>
        )}
      </section>

      <Link
        to="/emergency"
        className="card-soft flex items-center justify-between gap-3 p-5 transition-transform hover:-translate-y-0.5"
      >
        <span>
          <span className="kicker text-alert">{t.emergencyKicker}</span>
          <span className="mt-1 block font-display text-lg font-bold">{t.emergency}</span>
        </span>
        <span className="flex size-10 items-center justify-center rounded-full bg-blush font-display text-xl font-bold text-alert">
          !
        </span>
      </Link>

      <p className="pb-4 text-center text-xs text-muted-foreground">{t.disclaimer}</p>
    </main>
  );
}
