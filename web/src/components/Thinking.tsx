/**
 * Thinking — inline reasoning trace.
 *
 * Reasoning streams from providers like OpenAI's ``/responses`` API as a
 * sequence of sections, each beginning with a bold ``**Title**`` header.
 * ``splitSections`` (see ``@/utils/thinking``) parses the raw text into
 * ordered sections; each header is rendered as a styled run above its body.
 * Inline ``**bold**`` runs inside the body are NOT Markdown-rendered —
 * reasoning is rarely complex prose; only the section headers get emphasis.
 */
import { splitSections } from '@/utils/thinking'

interface ThinkingProps {
  content: string
  isStreaming?: boolean
}

export function Thinking({ content }: ThinkingProps) {
  const sections = splitSections(content)

  return (
    <div className="my-2 space-y-2 font-mono text-xs leading-relaxed text-(--color-text-2)">
      {sections.map((s, i) => (
        <div key={i}>
          {s.header && (
            <p className="mb-1 font-semibold text-(--color-text)">{s.header}</p>
          )}
          {s.body && <p className="whitespace-pre-wrap">{s.body}</p>}
        </div>
      ))}
    </div>
  )
}
