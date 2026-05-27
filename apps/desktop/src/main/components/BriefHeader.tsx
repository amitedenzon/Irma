interface BriefHeaderProps {
  generatedAt: string;
  velocity: string;
}

export function BriefHeader({ generatedAt, velocity }: BriefHeaderProps) {
  const when = new Date(generatedAt);
  const stamp = isNaN(when.getTime())
    ? generatedAt
    : when.toLocaleString(undefined, {
        weekday: "short",
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });

  return (
    <header className="flex flex-col gap-2">
      <div className="text-xs uppercase tracking-widest text-nofari-mute">
        Standup brief · {stamp}
      </div>
      <p className="text-lg leading-snug text-nofari-text">{velocity}</p>
    </header>
  );
}
