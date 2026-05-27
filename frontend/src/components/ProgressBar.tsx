interface ProgressBarProps {
  value: number
  label?: string
}

export const ProgressBar = ({ value, label }: ProgressBarProps) => (
  <div className="w-full">
    {label && <p className="text-sm text-zinc-500 dark:text-zinc-400 mb-1">{label}</p>}
    <div className="w-full bg-zinc-200 dark:bg-white/10 rounded-full h-3">
      <div
        className="bg-blue-600 h-3 rounded-full transition-all duration-300"
        style={{ width: `${Math.min(100, Math.max(0, value))}%` }}
      />
    </div>
    <p className="text-xs text-zinc-400 mt-1 text-right">{value}%</p>
  </div>
)
