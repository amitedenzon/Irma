interface NarrativeProps {
  text: string;
}

export function Narrative({ text }: NarrativeProps) {
  return (
    <section className="border-l-2 border-nofari-indigo pl-4 py-1">
      <p className="text-base leading-relaxed text-nofari-text italic">{text}</p>
    </section>
  );
}
