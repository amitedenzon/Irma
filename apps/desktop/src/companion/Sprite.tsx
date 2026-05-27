import type { CSSProperties } from "react";
import type { AgentState, SpriteManifest } from "../lib/types";
import { useSpriteAnimation } from "./useSpriteAnimation";

const PLACEHOLDER_SIZE = 80; // window is 96×96; 8px breathing room each side

const PLACEHOLDER_BG: Record<AgentState, string> = {
  idle: "radial-gradient(circle at 50% 42%, #9ea3ff 0%, #4b53d8 65%, #2a2f7a 100%)",
  observing: "radial-gradient(circle at 50% 42%, #8ff0e2 0%, #2da594 65%, #154a45 100%)",
  thinking: "radial-gradient(circle at 50% 42%, #d6b4ff 0%, #7b3fce 65%, #321b58 100%)",
  alert: "radial-gradient(circle at 50% 42%, #ffcd8a 0%, #d77b2a 65%, #5a300c 100%)",
};

const PLACEHOLDER_ANIM: Record<AgentState, string> = {
  idle: "nofari-pulse 1.6s ease-in-out infinite",
  observing: "nofari-scan 1.2s ease-out infinite",
  thinking: "nofari-shimmer 1s ease-in-out infinite",
  alert: "nofari-blink 0.6s steps(2, end) infinite",
};

interface SpriteProps {
  state: AgentState;
  manifest: SpriteManifest;
  sheetAvailable: boolean;
}

export function Sprite({ state, manifest, sheetAvailable }: SpriteProps) {
  const spec = manifest.states[state];
  const { frameIndex } = useSpriteAnimation(spec.frames.length, spec.fps);
  const frame = spec.frames[frameIndex] ?? spec.frames[0];

  if (sheetAvailable) {
    const sheetStyle: CSSProperties = {
      width: manifest.frameWidth,
      height: manifest.frameHeight,
      backgroundImage: `url(/sprites/${manifest.image})`,
      backgroundPosition: `${-(frame * manifest.frameWidth)}px 0`,
      backgroundRepeat: "no-repeat",
      imageRendering: "pixelated",
      userSelect: "none",
    };
    return <div style={sheetStyle} aria-label={`Nofari sprite — ${state}`} />;
  }

  // Pure inline styles — no Tailwind dependency. 80×80 centered in the
  // 96×96 window gives a soft visual margin around the sprite.
  const placeholderStyle: CSSProperties = {
    width: PLACEHOLDER_SIZE,
    height: PLACEHOLDER_SIZE,
    background: PLACEHOLDER_BG[state],
    animation: PLACEHOLDER_ANIM[state],
    borderRadius: "50%",
    boxShadow: "0 6px 22px rgba(0, 0, 0, 0.45)",
    userSelect: "none",
  };
  return (
    <div
      style={placeholderStyle}
      aria-label={`Nofari sprite — ${state} (placeholder)`}
    />
  );
}
