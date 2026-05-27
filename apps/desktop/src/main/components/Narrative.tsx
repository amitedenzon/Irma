interface NarrativeProps {
  text: string;
}

export function Narrative({ text }: NarrativeProps) {
  return (
    <section className="border-l-2 border-irma-indigo pl-4 py-1">
      <p className="text-base leading-relaxed text-irma-text italic">{text}</p>
    </section>
  );
}
