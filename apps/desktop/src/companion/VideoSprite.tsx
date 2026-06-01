/**
 * VideoSprite — renders a companion using transparent HEVC MOV videos.
 * All animations are preloaded; only the active one is visible.
 * HEVC with alpha is natively supported by macOS WKWebView.
 */
import { useEffect, useRef } from "react";

export interface VideoSpriteConfig {
  basePath: string;
  width: number;
  height: number;
  /** Fraction of container height the chicken occupies (feet stay on dock). */
  scale: number;
}

interface Props {
  config: VideoSpriteConfig;
  /** Behavior variant (dog/chicken variant or agent state) → mapped to a clip. */
  state: string;
  mirror?: boolean;
}

/** Map every variant → one of the 4 video files */
const STATE_TO_FILE: Record<string, string> = {
  idle:       "idle.mov",
  observing:  "walk.mov",
  thinking:   "peck.mov",
  alert:      "alert.mov",
  walk:       "walk.mov",
  walk_bark:  "walk.mov",
  sit:        "peck.mov",
  treat:      "peck.mov",
  stand:      "idle.mov",
  lay:        "peck.mov",
  cuddle:     "idle.mov",
  sit_bark:   "alert.mov",
};

const ALL_FILES = ["idle.mov", "walk.mov", "peck.mov", "alert.mov"];

export const CHICKEN_CONFIG: VideoSpriteConfig = {
  basePath: "/sprites/chicken",
  width: 128,
  height: 96,
  scale: 0.68, // smaller chicken; feet remain anchored to the dock
};

// Cache-bust version — bump this whenever a video file is replaced on disk.
const CACHE_V = "v6";

export function VideoSprite({ config, state, mirror = false }: Props) {
  const activeFile = STATE_TO_FILE[state] ?? "idle.mov";
  const videoRefs = useRef<Record<string, HTMLVideoElement | null>>({});

  useEffect(() => {
    for (const [file, el] of Object.entries(videoRefs.current)) {
      if (!el) continue;
      if (file === activeFile) {
        el.style.opacity = "1";
        // Continuous play (no currentTime reset) — the walk stride keeps
        // cycling across bursts so legs never snap back mid-step.
        void el.play().catch(() => {});
      } else {
        el.style.opacity = "0";
        el.pause();
      }
    }
  }, [activeFile]);

  return (
    <div
      style={{
        width: config.width,
        height: config.height,
        position: "relative",
        overflow: "hidden",
        transform: mirror ? "scaleX(-1)" : undefined,
      }}
    >
      {ALL_FILES.map((file) => (
        <video
          key={file}
          ref={(el) => { videoRefs.current[file] = el; }}
          src={`${config.basePath}/${file}?${CACHE_V}`}
          loop
          autoPlay
          muted
          playsInline
          style={{
            position: "absolute",
            bottom: 0,          // anchor feet to dock — same as sprite dogs
            left: "50%",
            transform: "translateX(-50%)",
            width: "auto",
            height: `${config.scale * 100}%`, // scaled down; feet stay at bottom
            objectFit: "contain",
            objectPosition: "bottom center",
            opacity: file === activeFile ? 1 : 0,
            transition: "opacity 0.08s",
            pointerEvents: "none",
          }}
        />
      ))}
    </div>
  );
}
