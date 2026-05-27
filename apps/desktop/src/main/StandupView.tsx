import type { StandupBrief } from "../lib/types";
import { BriefHeader } from "./components/BriefHeader";
import { Narrative } from "./components/Narrative";
import { BlockerList } from "./components/BlockerList";
import { ConflictList } from "./components/ConflictList";
import { ScheduleList } from "./components/ScheduleList";

interface StandupViewProps {
  brief: StandupBrief;
}

export function StandupView({ brief }: StandupViewProps) {
  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <BriefHeader generatedAt={brief.generated_at} velocity={brief.velocity} />
      <Narrative text={brief.narrative} />
      <section className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <BlockerList items={brief.blockers} />
        <ConflictList items={brief.conflicts} />
      </section>
      <ScheduleList items={brief.schedule} />
      <NextMove text={brief.recommendation} />
    </div>
  );
}

function NextMove({ text }: { text: string }) {
  return (
    <section className="border border-irma-border rounded-lg p-4 bg-irma-surface">
      <h3 className="text-xs uppercase tracking-widest text-irma-mute mb-2 flex items-center gap-2">
        <span className="inline-block w-2 h-2 rounded-full bg-irma-indigo" />
        Next move
      </h3>
      <p className="text-base leading-relaxed">{text}</p>
    </section>
  );
}
