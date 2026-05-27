import { useEffect, useState } from 'react'
import { getRosterUrl } from '../lib/apiClient'

interface RosterPreviewProps {
  fileId: string | null
}

// Short type word for the heading parenthetical, derived from the blob MIME.
const typeWord = (mime: string): string => {
  switch (mime) {
    case 'application/pdf':
      return 'PDF'
    case 'image/png':
      return 'PNG Image'
    case 'image/jpeg':
      return 'JPEG Image'
    default:
      return mime
  }
}

export const RosterPreview = ({ fileId }: RosterPreviewProps) => {
  const [src, setSrc] = useState<string | null>(null)
  const [mime, setMime] = useState('')
  const [error, setError] = useState(false)

  useEffect(() => {
    if (!fileId) return
    setError(false)
    let objectUrl: string | null = null
    // Fetch via credentials (auth-gated endpoint)
    fetch(getRosterUrl(fileId), { credentials: 'include' })
      .then((r) => {
        if (!r.ok) throw new Error('Not found')
        return r.blob()
      })
      .then((blob) => {
        objectUrl = URL.createObjectURL(blob)
        setMime(blob.type)
        setSrc(objectUrl)
      })
      .catch(() => setError(true))
    return () => {
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [fileId])

  // Heading shows the attachment type once known, e.g. "ROSTER (PDF)".
  const word = mime ? typeWord(mime) : ''
  const heading = (
    <p className="text-xs font-medium text-zinc-500 dark:text-zinc-400 uppercase tracking-wide mb-2">
      Roster{word && ` (${word})`}
    </p>
  )

  if (!fileId)
    return (
      <div>
        {heading}
        <div className="text-zinc-400 text-sm italic">No roster attached</div>
      </div>
    )
  if (error)
    return (
      <div>
        {heading}
        <div className="text-red-500 text-sm">Roster unavailable</div>
      </div>
    )
  if (!src)
    return (
      <div>
        {heading}
        <div className="text-zinc-400 text-sm">Loading…</div>
      </div>
    )

  const isPdf = mime === 'application/pdf'

  if (isPdf) {
    // <object>'s embedded viewer swallows clicks, so an overlay anchor sits on
    // top to make the whole preview open the PDF in a new tab.
    return (
      <div>
        {heading}
        <div className="relative h-48 w-full">
          <object
            data={src}
            type="application/pdf"
            className="h-full w-full rounded border border-zinc-200 dark:border-white/10"
            aria-label="Roster PDF preview"
          >
            <div className="text-zinc-500 text-sm">PDF preview not supported here.</div>
          </object>
          <a
            href={src}
            target="_blank"
            rel="noreferrer"
            aria-label="Open PDF in new tab"
            title="Open PDF in new tab"
            className="absolute inset-0 cursor-zoom-in"
          />
        </div>
      </div>
    )
  }

  return (
    <div>
      {heading}
      <a href={src} target="_blank" rel="noreferrer">
        <img
          src={src}
          alt="Roster preview"
          className="max-h-48 rounded border border-zinc-200 dark:border-white/10 object-contain cursor-zoom-in hover:opacity-90 transition"
        />
      </a>
    </div>
  )
}
