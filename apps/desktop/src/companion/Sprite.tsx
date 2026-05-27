import type { CSSProperties } from "react";
import type { AgentState, SpriteFrameSpec, SpriteManifest } from "../lib/types";
import { useSpriteAnimation } from "./useSpriteAnimation";

const PLACEHOLDER_SIZE = 80;

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
  spec: SpriteFrameSpec;
  manifest: SpriteManifest;
  sheetAvailable: boolean;
  fallbackState: AgentState;
  /** Flip the sprite horizontally — source art faces left, mirror for right. */
  mirror?: boolean;
}

export function Sprite({
  spec,
  manifest,
  sheetAvailable,
  fallbackState,
  mirror = false,
}: SpriteProps) {
  const { frameIndex } = useSpriteAnimation(spec.frames.length, spec.fps);
  const frame = spec.frames[frameIndex] ?? spec.frames[0];

  if (sheetAvailable) {
    const scale = manifest.scale ?? 1;
    const dispW = manifest.frameWidth * scale;
    const dispH = manifest.frameHeight * scale;
    const col = frame % manifest.columns;
    const row = Math.floor(frame / manifest.columns);
    const sheetStyle: CSSProperties = {
      width: dispW,
      height: dispH,
      backgroundImage: `url(/sprites/${manifest.image})`,
      backgroundPosition: `${-col * dispW}px ${-row * dispH}px`,
      backgroundSize: `${manifest.columns * dispW}px auto`,
      backgroundRepeat: "no-repeat",
      imageRendering: "pixelated",
      userSelect: "none",
      transform: mirror ? "scaleX(-1)" : undefined,
    };
    return <div style={sheetStyle} aria-label="Nofari sprite" />;
  }

  const placeholderStyle: CSSProperties = {
    width: PLACEHOLDER_SIZE,
    height: PLACEHOLDER_SIZE,
    background: PLACEHOLDER_BG[fallbackState],
    animation: PLACEHOLDER_ANIM[fallbackState],
    borderRadius: "50%",
    boxShadow: "0 6px 22px rgba(0, 0, 0, 0.45)",
    userSelect: "none",
  };
  return (
    <div
      style={placeholderStyle}
      aria-label={`Nofari sprite — ${fallbackState} (placeholder)`}
    />
  );
}
