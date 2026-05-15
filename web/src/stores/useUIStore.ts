/**
 * useUIStore — tiny client-state store for UI panels that live above the
 * TeamChatView and were previously owned by ``Sidebar``. Lifting state to a
 * shared store lets the topbar trigger them (per the wireframe redesign) and
 * keeps the Ctrl+M / Ctrl+S keyboard shortcuts working from any consumer.
 *
 * Mirrors the size and shape of ``useToastStore`` — Zustand + immer, no
 * persistence, no derived selectors.
 */
import { create } from 'zustand'
import { immer } from 'zustand/middleware/immer'

interface UIStore {
  wikiOpen: boolean
  schedulerOpen: boolean
  toggleWiki: () => void
  toggleScheduler: () => void
  closeWiki: () => void
  closeScheduler: () => void
}

export const useUIStore = create<UIStore>()(
  immer((set) => ({
    wikiOpen: false,
    schedulerOpen: false,
    toggleWiki: () => set((state) => { state.wikiOpen = !state.wikiOpen }),
    toggleScheduler: () => set((state) => { state.schedulerOpen = !state.schedulerOpen }),
    closeWiki: () => set((state) => { state.wikiOpen = false }),
    closeScheduler: () => set((state) => { state.schedulerOpen = false }),
  }))
)
