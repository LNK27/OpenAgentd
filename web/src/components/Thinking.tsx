/**
 * Thinking — inline reasoning trace.
 */

interface ThinkingProps {
  content: string
  isStreaming?: boolean
}

function splitHeader(content: string): { header: string | null; body: string } {
  const match = content.match(/^\s*\*\*([^*\n]+)\*\*\s*(?:\n+|$)([\s\S]*)$/)
  if (!match) return { header: null, body: content }
  return { header: match[1].trim(), body: match[2] }
}

export function Thinking({ content }: ThinkingProps) {
  const { header, body } = splitHeader(content)

  return (
    <div className="my-2 font-mono text-xs leading-relaxed text-(--color-text-2)">
      {header && <p className="mb-1 font-semibold text-(--color-text)">{header}</p>}
      {body.trim() && <p className="whitespace-pre-wrap">{body}</p>}
    </div>
  )
}
