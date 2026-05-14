/**
 * Pure helpers for the InputBar's @-mention picker.
 *
 * Kept in a separate module so InputBar.tsx can stay HMR-friendly under
 * react-refresh (which forbids non-component exports from .tsx files).
 */
import fuzzysort from 'fuzzysort'

/**
 * A workspace file or folder available to the user as an `@`-mention.
 * Paths are POSIX-separated and relative to the workspace root.
 */
export interface FileRef {
  path: string
  name: string
  type: 'file' | 'directory'
}

/**
 * Find an active `@token` immediately to the left of the caret.
 *
 * Returns the start/end indices in ``value`` and the partial token (the chars
 * typed after the `@`). Returns ``null`` when the caret is not inside an
 * `@`-mention context — that is, when:
 *   - there is no `@` before the caret, or
 *   - the `@` is not preceded by whitespace or string-start, or
 *   - the token contains whitespace (the mention has been "closed").
 *
 * This is the same heuristic used by opencode/Claude/Cursor: trigger on `@`
 * after whitespace, end the trigger on the next whitespace.
 */
export function findActiveMention(
  value: string,
  caret: number,
): { start: number; end: number; query: string } | null {
  // Scan left from the caret until we hit whitespace or `@`. Anything else
  // is part of the token-in-progress.
  let i = caret
  while (i > 0) {
    const ch = value.charAt(i - 1)
    if (ch === '@') {
      const before = i >= 2 ? value.charAt(i - 2) : ''
      const atStart = i === 1
      if (atStart || /\s/.test(before)) {
        return { start: i - 1, end: caret, query: value.slice(i, caret) }
      }
      return null
    }
    if (/\s/.test(ch)) return null
    i--
  }
  return null
}

/**
 * Find every `@mention` token in ``value`` that has been "committed" —
 * i.e. terminated by whitespace or end-of-string.
 *
 * Used by the highlight overlay to paint colored backgrounds behind each
 * mention. Callers may pass an ``activeRange`` to exclude the token at the
 * caret, so a chip doesn't materialise on every keystroke while the user
 * is still picking from the menu.
 *
 * Rules (mirror ``findActiveMention``):
 *   - `@` must be at the start of the string or after whitespace
 *     (so ``user@host.com`` is ignored).
 *   - The token runs from the `@` to the next whitespace.
 *   - A bare `@` with nothing after it is ignored.
 *
 * Returned ranges are sorted left-to-right and never overlap.
 */
export function findCommittedMentions(
  value: string,
  activeRange?: { start: number; end: number } | null,
): { start: number; end: number }[] {
  const out: { start: number; end: number }[] = []
  for (let i = 0; i < value.length; i++) {
    if (value.charAt(i) !== '@') continue
    const before = i > 0 ? value.charAt(i - 1) : ''
    if (i !== 0 && !/\s/.test(before)) continue

    // Walk forward to the next whitespace (or end).
    let j = i + 1
    while (j < value.length && !/\s/.test(value.charAt(j))) j++

    // Need at least one character after the `@` to be a real mention.
    if (j === i + 1) continue

    // Skip the actively-edited mention so the chip doesn't flash on every
    // keystroke. The picker already provides feedback there.
    if (activeRange && activeRange.start === i) continue

    out.push({ start: i, end: j })
    i = j // jump past this token to avoid double-matching inside it
  }
  return out
}

/**
 * Rank and filter a flat list of files/folders for the `@`-mention picker.
 *
 * Behaviour:
 *
 *  Empty query (just `@` typed):
 *    - Top-level folders (no slash in ``path``) first, alphabetically.
 *    - Then everything else in given order (files first, deeper dirs after).
 *    Makes the picker a discoverable folder browser when the user doesn't
 *    yet know what to type.
 *
 *  Non-empty query:
 *    Fuzzy *subsequence* match against the path. Each query character must
 *    appear in the path, in order, but not necessarily contiguously — so
 *    ``dockcom`` matches ``docker-compose.yml``. Backed by ``fuzzysort``,
 *    which scores consecutive runs and word-boundary matches highest.
 *
 *    On top of fuzzysort's score we apply a small directory bonus: a
 *    directory whose ``name`` (or path) matches gets surfaced above its
 *    children when scores are otherwise close. This preserves the
 *    "I typed `src` so I probably want the `src` directory" intuition.
 *
 * Pure and stable — same input always yields the same output. Safe to call
 * from a ``useMemo`` on every keystroke; cost is dominated by fuzzysort
 * which has been engineered for this exact workload.
 */
export function rankFileRefs(
  refs: readonly FileRef[],
  rawQuery: string,
  limit: number,
): FileRef[] {
  const query = rawQuery.trim()

  if (!query) {
    // Empty query: top-level folders first (so `@<Enter>` browses the
    // workspace root), then everything else in given order.
    const topDirs: FileRef[] = []
    const rest: FileRef[] = []
    for (const ref of refs) {
      if (ref.type === 'directory' && !ref.path.includes('/')) topDirs.push(ref)
      else rest.push(ref)
    }
    topDirs.sort((a, b) => a.name.localeCompare(b.name))
    return [...topDirs, ...rest].slice(0, limit)
  }

  // Fuzzysort scores in [0, 1] with higher = better. We adjust the score so
  // a directory whose own name is a strong match comes above its children
  // when the two are otherwise similar — fuzzysort doesn't know that
  // ``src`` (the dir) is a different concept from ``src/foo.ts``, but the
  // user typing ``src`` usually does mean the dir.
  //
  // Bonuses are small enough that they don't override a genuinely better
  // fuzzy match elsewhere (e.g. typing ``api`` still surfaces ``api.ts``
  // above an unrelated ``apidocs/`` dir).
  const lowerQuery = query.toLowerCase()
  const results = fuzzysort.go(query, refs, {
    key: 'path',
    // Over-fetch a little so the dir bonus can reshuffle the head.
    limit: limit * 2,
    threshold: 0.2, // drop very weak matches; tuned to feel snappy
  })

  const adjusted = results.map((r) => {
    const ref = r.obj
    let score = r.score
    if (ref.type === 'directory') {
      const lowerName = ref.name.toLowerCase()
      if (lowerName === lowerQuery) score += 0.5      // exact dir-name match
      else if (lowerName.startsWith(lowerQuery)) score += 0.15
      else score += 0.05                              // any dir match
    }
    return { ref, score }
  })

  adjusted.sort((a, b) => {
    if (a.score !== b.score) return b.score - a.score // higher score first
    // Tie-break: shorter path wins — closer to the workspace root.
    if (a.ref.path.length !== b.ref.path.length) {
      return a.ref.path.length - b.ref.path.length
    }
    return a.ref.path.localeCompare(b.ref.path)
  })

  return adjusted.slice(0, limit).map((s) => s.ref)
}
