import { X } from 'lucide-react'
import { useTeamStore } from '@/stores/useTeamStore'

export function PendingMessageQueue() {
  const allMessages = useTeamStore((s) => s._pendingMessages)
  const sessionId = useTeamStore((s) => s.sessionId)
  const messages = allMessages.filter((msg) => (msg.sessionId ?? null) === sessionId)
  const removePendingMessage = useTeamStore((s) => s.removePendingMessage)

  if (messages.length === 0) return null

  const handleRemove = (id: string) => {
    removePendingMessage(id)
  }

  return (
    <div className="flex flex-col gap-3">
      {messages.map((msg) => (
        <div key={msg.id} className="group flex justify-end">
          <div className="flex max-w-[78%] flex-col items-end gap-1.5">
            <div className="flex items-start gap-2">
              <div className="relative overflow-hidden rounded-sm border border-(--color-border) bg-(--color-surface) px-4 py-3 text-sm leading-relaxed text-(--color-text) opacity-75 shadow-sm">
                <p className="break-words whitespace-pre-wrap">{msg.content}</p>
              </div>
              <button
                onClick={() => handleRemove(msg.id)}
                aria-label="Cancel queued message"
                title="Cancel queued message"
                className="mt-1 rounded-full p-1 text-(--color-text-muted) opacity-70 transition-colors hover:bg-(--bg-key) hover:text-(--color-text) group-hover:opacity-100"
              >
                <X size={13} />
              </button>
            </div>
            <span className="pr-8 text-[11px] text-(--color-text-subtle)">Queued</span>
          </div>
        </div>
      ))}
    </div>
  )
}
