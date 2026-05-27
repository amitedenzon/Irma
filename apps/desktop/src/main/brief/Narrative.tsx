export function Narrative({ text }: { text: string }) {
  if (!text) return null;
  return (
    <section>
      <h3 className="text-xs uppercase tracking-widest text-irma-mute mb-2">
        Narrative
      </h3>
      <p className="text-sm leading-relaxed whitespace-pre-wrap">{text}</p>
    </section>
  );
}
