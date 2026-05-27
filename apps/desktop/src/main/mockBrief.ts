import type { StandupBrief } from "../lib/types";

/**
 * Phase 1 fixture demonstrating the cross-epic conflict the spec calls for
 * (CLAUDE.md §10): heavy video-world-model commit velocity colliding with a
 * fixed MIT DL coursework block. Replaced by /api/v1/standup in Phase 3.
 */
export const mockBrief: StandupBrief = {
  generated_at: new Date().toISOString(),
  velocity:
    "12 commits over the last 3 days, +1,420 / −618 lines. Momentum is concentrated on the video-world-model autoregressive guidance head.",
  blockers: [
    "Zero-shot eval pipeline blocked on GCS quota — retry after 2026-05-28 06:00 UTC.",
  ],
  conflicts: [
    "Heavy commit velocity on the Zero-Shot Video World Model, but a 4-hour MIT 6.S191 block tomorrow (16:00–20:00) — consider freezing code tonight to prep coursework.",
  ],
  schedule: [
    {
      ts: "2026-05-28T16:00:00Z",
      title: "MIT 6.S191 — Deep Generative Models",
      epic: "MIT DL & Bar-Ilan M.Sc",
    },
    {
      ts: "2026-05-29T09:30:00Z",
      title: "Bar-Ilan M.Sc advisor sync",
      epic: "MIT DL & Bar-Ilan M.Sc",
    },
    {
      ts: "2026-05-30T14:00:00Z",
      title: "Video-WM ablation review",
      epic: "Zero-Shot Video World Model",
    },
  ],
  recommendation:
    "Freeze video-WM code by 22:00 tonight; spend the morning on the MIT DL pset before the 16:00 block.",
  narrative:
    "You're shipping fast on the world model — that's the good news. The collision tomorrow is the real signal: a four-hour coursework block while a long-running ablation is still mid-flight. Park the ablation tonight, swap context cleanly, and treat the MIT block as protected. I'll reassemble the brief when the next commit window opens.",
};
