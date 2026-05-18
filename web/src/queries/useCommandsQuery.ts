/** TanStack Query hook for the slash-command picker. */
import { useQuery } from '@tanstack/react-query'

import { listCommands } from '@/api/client'

import { queryKeys } from './keys'

export function useCommandsQuery() {
  return useQuery({
    queryKey: queryKeys.commands.list(),
    queryFn: listCommands,
    // Commands live on disk and rarely change during a session.
    staleTime: 60_000,
  })
}
