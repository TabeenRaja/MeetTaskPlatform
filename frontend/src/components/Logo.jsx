export function LogoMark({ size = 40 }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className="shrink-0"
      aria-hidden="true"
      focusable="false"
    >
      <rect width="64" height="64" rx="15" fill="#1F5C99" />
      <path
        d="M20 15.5h24a6.5 6.5 0 0 1 6.5 6.5v13a6.5 6.5 0 0 1-6.5 6.5H29L20.5 50v-8.5H20a6.5 6.5 0 0 1-6.5-6.5V22a6.5 6.5 0 0 1 6.5-6.5Z"
        fill="#FFFFFF"
      />
      <path
        d="M29.5 22.5h13.5M20 29.5h23M20 35.5h16"
        stroke="#1F5C99"
        strokeWidth="2.6"
        strokeLinecap="round"
      />
      <path
        d="m18.5 23 2.5 2.5 4-4.8"
        stroke="#109B79"
        strokeWidth="2.1"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

export function Logo({ dark = false, size = 40, tagline = true }) {
  return (
    <div className="flex items-center gap-3">
      <LogoMark size={size} />
      <div className="leading-none">
        <div className={`text-[21px] font-bold tracking-tight ${dark ? 'text-white' : 'text-slate-900'}`}>
          MeetTask
        </div>
        {tagline && (
          <div className={`mt-1 font-mono text-[9px] uppercase tracking-[0.25em] ${dark ? 'text-slate-400' : 'text-slate-500'}`}>
            Intelligence
          </div>
        )}
      </div>
    </div>
  )
}
