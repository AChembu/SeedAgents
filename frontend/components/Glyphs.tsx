"use client";

export function SeedlingMark({ size = 22 }: { size?: number }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      aria-hidden
      style={{ display: "block", flexShrink: 0 }}
    >
      <path d="M12 22 V11" stroke="#1A1F12" strokeWidth="1.1" strokeLinecap="round" />
      <path
        d="M12 14 C 7.5 14, 5.5 11, 5 6.5 C 9.5 7.2, 11.2 9.5, 12 14 Z"
        fill="#3E4A2A"
      />
      <path
        d="M12 16 C 16.5 16, 18.5 13, 19 8.5 C 14.5 9.2, 12.8 11.5, 12 16 Z"
        fill="#6E7E47"
      />
      <path d="M7 22 H 17" stroke="#1A1F12" strokeWidth="0.8" strokeLinecap="round" opacity="0.5" />
    </svg>
  );
}

export function ArrowGlyph({ size = 16 }: { size?: number }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      aria-hidden
      style={{ display: "block", flexShrink: 0 }}
    >
      <path d="M4 12 H 20" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
      <path
        d="M14 6 L 20 12 L 14 18"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />
    </svg>
  );
}
