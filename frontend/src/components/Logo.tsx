/** Biểu trưng MeetFlow: ô vuông bo góc nền chuyển màu, có quầng sáng nhẹ. */
export default function Logo({ size = 'md' }: { size?: 'md' | 'lg' }) {
  const box = size === 'lg' ? 'size-12 rounded-2xl text-xl' : 'size-8 rounded-xl text-sm'
  return (
    <span
      aria-hidden="true"
      className={`btn-primary inline-flex shrink-0 items-center justify-center font-bold tracking-tight ${box}`}
    >
      M
    </span>
  )
}
