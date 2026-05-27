interface ConflictListProps {
  items: string[];
}

export function ConflictList({ items }: ConflictListProps) {
  return (
    <section className="border border-irma-border rounded-lg p-4 bg-irma-surface">
      <h3 className="text-xs uppercase tracking-widest text-irma-mute mb-3 flex items-center gap-2">
        <span className="inline-block w-2 h-2 rounded-full bg-irma-amber" />
        Cross-epic conflicts
      </h3>
      {items.length === 0 ? (
        <p className="text-sm text-irma-mute">No collisions.</p>
      ) : (
        <ul className="space-y-2 text-sm">
          {items.map((c, i) => (
            <li key={i} className="leading-relaxed">
              {c}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
