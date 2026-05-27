import { useEffect, useState } from "react";

/**
 * Drives a sprite-sheet frame index from a requestAnimationFrame loop.
 *
 * The hook is intentionally cheap: it owns one rAF callback and one piece of
 * React state. The placeholder sprite ignores `frameIndex` and animates via
 * CSS keyframes — calling this hook is still safe (and idempotent under
 * `frames.length <= 1`).
 */
export function useSpriteAnimation(
  frameCount: number,
  fps: number,
): { frameIndex: number } {
  const [frameIndex, setFrameIndex] = useState(0);

  useEffect(() => {
    if (frameCount <= 1 || fps <= 0) {
      setFrameIndex(0);
      return;
    }
    let raf = 0;
    const start = performance.now();
    const tick = (now: number): void => {
      const elapsedSec = (now - start) / 1000;
      const idx = Math.floor(elapsedSec * fps) % frameCount;
      setFrameIndex(idx);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [frameCount, fps]);

  return { frameIndex };
}
