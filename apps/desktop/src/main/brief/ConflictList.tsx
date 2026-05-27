export function ConflictList({ items }: { items: string[] }) {
  if (items.length === 0) return null;
  return (
    <section className="border border-irma-amber/40 rounded-lg p-4 bg-irma-amber/5">
      <h3 className="text-xs uppercase tracking-widest text-irma-amber mb-2">
        Conflicts
      </h3>
      <ul className="text-sm space-y-1 list-disc list-inside">
        {items.map((c, i) => (
          <li key={i}>{c}</li>
        ))}
      </ul>
    </section>
  );
}
