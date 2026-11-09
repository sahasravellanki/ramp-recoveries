export function Mark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 16 16" className={className} aria-hidden>
      <rect width="16" height="16" rx="4" fill="#1c1c1c" />
      <path
        d="M3.5 10.6 8 4.4l4.5 6.2"
        fill="none"
        stroke="#e4f222"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
