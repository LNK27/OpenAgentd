import { useState } from 'react'
import { ArrowLeft, Bell, BellRing } from 'lucide-react'
import { Link } from '@tanstack/react-router'

import {
  areDesktopNotificationsEnabled,
  sendDesktopNotification,
  setDesktopNotificationsEnabled,
} from '@/lib/desktop-notifications'
import { useIsMobile } from '@/hooks/use-mobile'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'

export function NotificationSettingsPage() {
  const isMobile = useIsMobile()
  const [enabled, setEnabled] = useState(() => areDesktopNotificationsEnabled())
  const [testing, setTesting] = useState(false)
  const [testMessage, setTestMessage] = useState<string | null>(null)

  const handleEnabledChange = (checked: boolean) => {
    setEnabled(checked)
    setDesktopNotificationsEnabled(checked)
  }

  const handleTest = async () => {
    setTesting(true)
    setTestMessage(null)
    try {
      const result = await sendDesktopNotification(
        {
          kind: 'assistant_done',
          title: 'OpenAgentd notification test',
          body: 'Desktop notifications are working.',
        },
        { force: true },
      )
      setTestMessage(result.message)
    } finally {
      setTesting(false)
    }
  }

  return (
    <>
      <header className="sticky top-0 z-10 flex h-14 shrink-0 items-center gap-3 border-b border-(--color-border) bg-(--bg-page) px-4">
        {isMobile && (
          <Link
            to="/settings"
            className="flex h-11 w-11 shrink-0 items-center justify-center rounded-md text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
            aria-label="Back to settings"
          >
            <ArrowLeft size={14} />
          </Link>
        )}
        <Bell size={15} className="shrink-0 text-(--color-text-muted)" aria-hidden="true" />
        <h1 className="flex-1 truncate text-sm font-semibold text-(--color-text)">Notifications</h1>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-2xl space-y-5 p-6">
          <p className="text-sm leading-relaxed text-(--color-text-muted)">
            Desktop notifications appear when OpenAgentd is running in the
            desktop app and the window is hidden, minimized, or not focused.
          </p>

          <section className="space-y-3 rounded-xl border border-(--color-border) bg-(--bg-card) p-4">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-(--color-text-muted)">
              Status
            </h2>

            <label className="flex cursor-pointer items-center gap-3 text-sm">
              <Switch
                checked={enabled}
                onCheckedChange={handleEnabledChange}
              />
              <span className="text-(--color-text)">Enabled</span>
            </label>
            <p className="text-xs text-(--color-text-muted)">
              OpenAgentd will notify you when an assistant finishes responding,
              a background task completes, or a reminder fires. Notifications
              are skipped while the app window is focused.
            </p>
          </section>

          <section className="space-y-3 rounded-xl border border-(--color-border) bg-(--bg-card) p-4">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-(--color-text-muted)">
              Test
            </h2>
            <p className="text-xs text-(--color-text-muted)">
              Send one notification now to confirm OS permissions and desktop
              integration are working.
            </p>
            <Button size="sm" onClick={handleTest} disabled={!enabled || testing}>
              <BellRing size={12} aria-hidden="true" />
              {testing ? 'Sending…' : 'Send test notification'}
            </Button>
            {testMessage && (
              <p className="text-xs text-(--color-text-muted)" role="status">
                {testMessage}
              </p>
            )}
          </section>
        </div>
      </div>
    </>
  )
}
