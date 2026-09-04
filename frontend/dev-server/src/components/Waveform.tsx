const BARS = [
  { h: 40, d: 1, c: "bg-brand/70", delay: 0 },
  { h: 80, d: 0.9, c: "bg-brand/70", delay: 0.1 },
  { h: 100, d: 1.1, c: "bg-brand/70", delay: 0.2 },
  { h: 60, d: 0.8, c: "bg-mint", delay: 0.15 },
  { h: 90, d: 1, c: "bg-mint", delay: 0.3 },
  { h: 50, d: 0.95, c: "bg-brand/70", delay: 0.05 },
  { h: 75, d: 1.05, c: "bg-brand/70", delay: 0.25 },
  { h: 45, d: 0.9, c: "bg-mint", delay: 0.35 },
];

export function Waveform({ active = true }: { active?: boolean }) {
  return (
    <div className="flex h-12 flex-1 items-end justify-end gap-[3px]">
      {BARS.map((b, i) => (
        <span
          key={i}
          className={"w-1.5 rounded-full " + b.c}
          style={{
            height: `${b.h}%`,
            animation: active ? `wave ${b.d}s ease-in-out ${b.delay}s infinite` : undefined,
            opacity: active ? 1 : 0.35,
          }}
        />
      ))}
    </div>
  );
}
