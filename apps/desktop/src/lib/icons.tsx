/**
 * Pixel-art icon set. 32×32 native grid, scales pixel-perfect at any size.
 * Style matches streamline-pixel: 2px stroke, no anti-aliasing, blocky shapes.
 * All icons use currentColor; size via the `size` prop or className width.
 */

import type { CSSProperties } from "react";

type IconProps = { size?: number; className?: string; title?: string };

const baseStyle = (size: number): CSSProperties => ({
  width: size,
  height: size,
  imageRendering: "pixelated",
  shapeRendering: "crispEdges",
  flexShrink: 0,
});

function Wrap({ size = 16, className, title, children }: IconProps & { children: React.ReactNode }) {
  return (
    <svg
      viewBox="0 0 32 32"
      xmlns="http://www.w3.org/2000/svg"
      style={baseStyle(size)}
      className={className}
      aria-label={title}
      role={title ? "img" : "presentation"}
    >
      {title && <title>{title}</title>}
      {children}
    </svg>
  );
}

// Helper to draw 2x2 "pixels" inside the 32x32 grid for chunkier look.
const px = (x: number, y: number, w = 2, h = 2) => (
  <rect x={x * 2} y={y * 2} width={w * 2} height={h * 2} fill="currentColor" />
);

export const IconFolder = (p: IconProps) => (
  <Wrap {...p}>
    {/* folder tab */}
    {px(2, 5, 5, 2)}
    {/* folder body */}
    {px(2, 7, 12, 8)}
    {/* inner highlight stripe */}
    <rect x={6} y={18} width={20} height={2} fill="currentColor" opacity="0.4" />
  </Wrap>
);

export const IconCheck = (p: IconProps) => (
  <Wrap {...p}>
    {px(3, 8)} {px(4, 9)} {px(5, 10)} {px(6, 11)}
    {px(7, 10)} {px(8, 9)} {px(9, 8)} {px(10, 7)} {px(11, 6)} {px(12, 5)}
  </Wrap>
);

export const IconBox = (p: IconProps) => (
  <Wrap {...p}>
    {/* hollow square */}
    <rect x={6} y={6} width={20} height={2} fill="currentColor" />
    <rect x={6} y={24} width={20} height={2} fill="currentColor" />
    <rect x={6} y={6} width={2} height={20} fill="currentColor" />
    <rect x={24} y={6} width={2} height={20} fill="currentColor" />
  </Wrap>
);

export const IconClock = (p: IconProps) => (
  <Wrap {...p}>
    {/* simple round-ish clock face */}
    <rect x={10} y={4} width={12} height={2} fill="currentColor" />
    <rect x={10} y={26} width={12} height={2} fill="currentColor" />
    <rect x={4} y={10} width={2} height={12} fill="currentColor" />
    <rect x={26} y={10} width={2} height={12} fill="currentColor" />
    <rect x={6} y={6} width={2} height={2} fill="currentColor" />
    <rect x={24} y={6} width={2} height={2} fill="currentColor" />
    <rect x={6} y={24} width={2} height={2} fill="currentColor" />
    <rect x={24} y={24} width={2} height={2} fill="currentColor" />
    {/* hands */}
    <rect x={14} y={10} width={2} height={6} fill="currentColor" />
    <rect x={14} y={14} width={6} height={2} fill="currentColor" />
  </Wrap>
);

export const IconFlag = (p: IconProps) => (
  <Wrap {...p}>
    {/* pole */}
    <rect x={6} y={4} width={2} height={24} fill="currentColor" />
    {/* flag */}
    <rect x={8} y={6} width={16} height={2} fill="currentColor" />
    <rect x={22} y={8} width={2} height={2} fill="currentColor" />
    <rect x={8} y={10} width={16} height={2} fill="currentColor" />
    <rect x={8} y={12} width={14} height={2} fill="currentColor" />
  </Wrap>
);

export const IconBell = (p: IconProps) => (
  <Wrap {...p}>
    {/* bell crown */}
    {px(7, 3)} {px(8, 3)}
    {/* bell body */}
    <rect x={10} y={8} width={12} height={2} fill="currentColor" />
    <rect x={8} y={10} width={16} height={2} fill="currentColor" />
    <rect x={8} y={12} width={16} height={10} fill="currentColor" />
    <rect x={6} y={22} width={20} height={2} fill="currentColor" />
    {/* clapper */}
    <rect x={14} y={24} width={4} height={4} fill="currentColor" />
  </Wrap>
);

export const IconTerminal = (p: IconProps) => (
  <Wrap {...p}>
    {/* screen frame */}
    <rect x={2} y={4} width={28} height={2} fill="currentColor" />
    <rect x={2} y={26} width={28} height={2} fill="currentColor" />
    <rect x={2} y={4} width={2} height={24} fill="currentColor" />
    <rect x={28} y={4} width={2} height={24} fill="currentColor" />
    {/* > prompt */}
    <rect x={6} y={12} width={2} height={2} fill="currentColor" />
    <rect x={8} y={14} width={2} height={2} fill="currentColor" />
    <rect x={10} y={16} width={2} height={2} fill="currentColor" />
    <rect x={8} y={18} width={2} height={2} fill="currentColor" />
    <rect x={6} y={20} width={2} height={2} fill="currentColor" />
    {/* underscore cursor */}
    <rect x={14} y={20} width={10} height={2} fill="currentColor" />
  </Wrap>
);

export const IconPlus = (p: IconProps) => (
  <Wrap {...p}>
    <rect x={14} y={6} width={4} height={20} fill="currentColor" />
    <rect x={6} y={14} width={20} height={4} fill="currentColor" />
  </Wrap>
);

export const IconChevronRight = (p: IconProps) => (
  <Wrap {...p}>
    {px(10, 6)} {px(12, 8)} {px(14, 10)} {px(16, 12)}
    {px(14, 14)} {px(12, 16)} {px(10, 18)}
  </Wrap>
);

export const IconChevronDown = (p: IconProps) => (
  <Wrap {...p}>
    {px(6, 10)} {px(8, 12)} {px(10, 14)}
    {px(12, 16)}
    {px(14, 14)} {px(16, 12)} {px(18, 10)}
  </Wrap>
);

export const IconX = (p: IconProps) => (
  <Wrap {...p}>
    {px(5, 5)} {px(7, 7)} {px(9, 9)} {px(11, 11)} {px(13, 13)}
    {px(11, 5)} {px(9, 7)} {px(7, 9)} {px(5, 11)} {px(13, 5)} {px(15, 7)}
    {px(15, 11)} {px(13, 9)} {px(11, 13)} {px(9, 11)} {px(7, 13)}
  </Wrap>
);

export const IconRefresh = (p: IconProps) => (
  <Wrap {...p}>
    <rect x={8} y={6} width={12} height={2} fill="currentColor" />
    <rect x={6} y={8} width={2} height={4} fill="currentColor" />
    <rect x={20} y={8} width={2} height={4} fill="currentColor" />
    <rect x={4} y={12} width={2} height={4} fill="currentColor" />
    <rect x={22} y={6} width={4} height={2} fill="currentColor" />
    {/* arrow head */}
    <rect x={2} y={14} width={2} height={2} fill="currentColor" />
    <rect x={6} y={14} width={2} height={2} fill="currentColor" />
    {/* return stroke (lower mirror) */}
    <rect x={10} y={20} width={12} height={2} fill="currentColor" />
    <rect x={10} y={18} width={2} height={4} fill="currentColor" />
    <rect x={24} y={16} width={2} height={4} fill="currentColor" />
    <rect x={26} y={18} width={2} height={2} fill="currentColor" />
    <rect x={22} y={18} width={2} height={2} fill="currentColor" />
  </Wrap>
);

export const IconSpark = (p: IconProps) => (
  <Wrap {...p}>
    {/* 4-point pixel sparkle */}
    <rect x={14} y={2} width={4} height={6} fill="currentColor" />
    <rect x={14} y={24} width={4} height={6} fill="currentColor" />
    <rect x={2} y={14} width={6} height={4} fill="currentColor" />
    <rect x={24} y={14} width={6} height={4} fill="currentColor" />
    <rect x={12} y={12} width={8} height={8} fill="currentColor" />
  </Wrap>
);

export const IconArchive = (p: IconProps) => (
  <Wrap {...p}>
    <rect x={4} y={6} width={24} height={4} fill="currentColor" />
    <rect x={6} y={12} width={20} height={2} fill="currentColor" />
    <rect x={6} y={26} width={20} height={2} fill="currentColor" />
    <rect x={6} y={12} width={2} height={16} fill="currentColor" />
    <rect x={24} y={12} width={2} height={16} fill="currentColor" />
    <rect x={12} y={16} width={8} height={2} fill="currentColor" />
  </Wrap>
);

export const IconTrash = (p: IconProps) => (
  <Wrap {...p}>
    <rect x={10} y={4} width={12} height={2} fill="currentColor" />
    <rect x={6} y={8} width={20} height={2} fill="currentColor" />
    <rect x={8} y={10} width={16} height={2} fill="currentColor" />
    <rect x={8} y={12} width={2} height={16} fill="currentColor" />
    <rect x={22} y={12} width={2} height={16} fill="currentColor" />
    <rect x={8} y={28} width={16} height={2} fill="currentColor" />
    <rect x={12} y={14} width={2} height={12} fill="currentColor" />
    <rect x={18} y={14} width={2} height={12} fill="currentColor" />
  </Wrap>
);

export const IconPencil = (p: IconProps) => (
  <Wrap {...p}>
    <rect x={20} y={4} width={4} height={2} fill="currentColor" />
    <rect x={22} y={6} width={4} height={2} fill="currentColor" />
    <rect x={18} y={8} width={2} height={2} fill="currentColor" />
    <rect x={20} y={8} width={4} height={2} fill="currentColor" />
    {/* pencil shaft going down-left */}
    <rect x={16} y={10} width={2} height={2} fill="currentColor" />
    <rect x={14} y={12} width={2} height={2} fill="currentColor" />
    <rect x={12} y={14} width={2} height={2} fill="currentColor" />
    <rect x={10} y={16} width={2} height={2} fill="currentColor" />
    <rect x={8} y={18} width={2} height={2} fill="currentColor" />
    <rect x={6} y={20} width={2} height={2} fill="currentColor" />
    {/* tip + smudge */}
    <rect x={4} y={22} width={4} height={4} fill="currentColor" />
    <rect x={4} y={26} width={2} height={2} fill="currentColor" />
  </Wrap>
);

export const IconCalendar = (p: IconProps) => (
  <Wrap {...p}>
    <rect x={4} y={6} width={24} height={2} fill="currentColor" />
    <rect x={4} y={26} width={24} height={2} fill="currentColor" />
    <rect x={4} y={6} width={2} height={22} fill="currentColor" />
    <rect x={26} y={6} width={2} height={22} fill="currentColor" />
    <rect x={4} y={12} width={24} height={2} fill="currentColor" />
    {/* hangers */}
    <rect x={8} y={2} width={2} height={6} fill="currentColor" />
    <rect x={22} y={2} width={2} height={6} fill="currentColor" />
    {/* day cells */}
    <rect x={9} y={17} width={4} height={3} fill="currentColor" />
    <rect x={14} y={17} width={4} height={3} fill="currentColor" />
    <rect x={19} y={17} width={4} height={3} fill="currentColor" />
  </Wrap>
);
