export function LogoMark({ size = 40 }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      {/* Main Blue Rounded Square Background */}
      <rect x="2" y="10" width="52" height="52" rx="14" fill="#1D66B8" />

      {/* White 'M' Lettermark */}
      <path
        d="M14 48V25C14 23.5 15.2 22.5 16.5 23.2L28 32.5C28.8 33.1 29.2 33.1 30 32.5L41.5 23.2C42.8 22.5 44 23.5 44 25V48"
        stroke="#FFFFFF"
        strokeWidth="6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />

      {/* Top Right Floating Light Blue Checkmark Badge */}
      <circle cx="50" cy="14" r="11" fill="#50C8FF" stroke="#FFFFFF" strokeWidth="2" />

      {/* Dark Checkmark Icon */}
      <path
        d="M44.5 14L48.5 18L55.5 10.5"
        stroke="#0F3866"
        strokeWidth="3"
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
          Meet<span className={dark ? 'text-sky-400' : 'text-[#1D66B8]'}>Task</span>
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