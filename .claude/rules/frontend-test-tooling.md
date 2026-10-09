---
paths:
  - "frontend/**/*.test.ts"
  - "frontend/**/*.test.tsx"
  - "frontend/vite.config.*"
  - "frontend/vitest.config.*"
  - "frontend/tests/**"
  - "frontend/src/pages/DashboardPage.tsx"
---

### Frontend coverage — known limitations and solutions

**Problem 1 — `/* istanbul ignore next */` ignored by v8:**
esbuild strips comments before v8 instruments. Use instead:
```
/* v8 ignore next -- @preserve */
```
The `-- @preserve` forces esbuild to treat the comment as a "legal comment".
Source: [Vitest PR #2496](https://github.com/vitest-dev/vitest/pull/2496)

**Problem 2 — RETRACTED, was a misdiagnosis (kept as a cautionary example):**
A branch gap in `commission.ts` (`weekendRate ?? aboveRate`) was long attributed to a suspected
`ast-v8-to-istanbul` nested-ternary double-counting bug ([vitest#10394](https://github.com/vitest-dev/vitest/issues/10394)),
with the branch threshold set to 94% to tolerate it and a claim that "JSON canonical = 100%".
That claim was never verified against the raw `coverage/coverage-final.json` — when actually
checked, the JSON showed the exact same `[8, 0]` branch count as the text reporter (no
discrepancy at all). The real cause: every test called the deprecated `computeRevolutFXCommission`
alias, which hardcodes `weekendRate: 0.01` — nothing ever exercised the `?? aboveRate` fallback
with a `null` weekendRate. One test added, gap closed, no tool bug involved. The suite is now at
literal 100% branches (see below).
**Lesson:** before attributing a coverage gap to a "known tool bug," check the raw
`coverage-final.json` branch counts directly — a gap that survives from the text reporter into
the JSON is not a reporting artifact, it's a real missing test.

**Problem 3 — Istanbul provider via config doesn't load:**
Bug [#8165](https://github.com/vitest-dev/vitest/issues/8165). Workaround: pass `--coverage.provider=istanbul` via CLI.

**Problem 4 — a leftover `mockRejectedValueOnce`/`mockResolvedValueOnce` silently corrupts a
later, unrelated test (looks like a v8 coverage artifact, but isn't one):**
`vi.clearAllMocks()` in `beforeEach` clears call history (`mock.calls`, `mock.results`) but does
**not** drain a queued one-time implementation set via `mockResolvedValueOnce`/
`mockRejectedValueOnce` — only `mockReset()`/`resetAllMocks()` does that. If a test queues a
one-time mock for a call that (after a refactor) its own code path no longer makes, that queued
value stays put and silently attaches to the **next** test that makes a real call to the same
mocked function — even in a different `describe` block. Because many tests in this codebase use
weak assertions (`expect(screen.getByText('Administration système')).toBeTruthy()` — true
regardless of what the code actually did), the corrupted test still passes, but the code path it
was meant to exercise (e.g. a `setTimeout` callback gated behind a successful API call) never
runs, so its lines/branches silently drop out of coverage with no failing test to point at why.

**Symptom:** a block of code shows uncovered in a full-file/full-suite run but covered when the
one relevant test is run alone via `-t` — this looks exactly like a v8/vitest coverage-merging
artifact, but is not.

**How to diagnose:** add temporary `console.log` at the entry of the suspect function and its
catch block, run with `--reporter=verbose`, and read the interleaved stdout across the *whole*
file (not just the target test) — the log reveals the real, unexpected value being caught (e.g.
an error message from a completely different, earlier test) instead of the expected one.

**Fix:** every test that queues a `mockResolvedValueOnce`/`mockRejectedValueOnce` must actually
drive the code path to consume it within that same test, and assert on the resulting behaviour —
not just `toBeTruthy()` on unrelated static text. When a refactor changes how a flow is triggered
(e.g. a click now opens a confirmation modal instead of calling the API immediately), update
every test that relied on the old immediate call. A leftover queued mock from a stale test is
caught by neither TypeScript, ESLint, nor a passing test suite — only by noticing the coverage gap.

**Rule — `vi.mock` must be at the top level of the test file:**
Vitest hoists `vi.mock` to the top of the module. A `vi.mock` nested inside `it()` or `describe()`
produces a warning — will become an error in a future version.
To change a mock value within a test: use `mockReturnValue` in `beforeEach`.

**Problem 5 — position-based selectors (`getAllByText(...)[.length - 1]`, `.slice(-3)`,
`inputs[0]`) silently break when new, unrelated content is added elsewhere on the same page:**
`GlobalConfigPage.tsx` hosts several independent managers (TTF rate, `CommissionManager`,
`ProductManager`, `RegionManager`) stacked as sibling `Card`s. Several pre-existing tests
targeted "the button/input I care about" by position — `saveBtns[saveBtns.length - 1]` (assumed
last "Enregistrer" on the page = the one just opened), `numberInputs.slice(-3)` (assumed the
last 3 number inputs = the FX panel's three fields). Adding the "Indicateurs macro" card (with
its own always-rendered `SettingField` "Enregistrer" buttons and a numeric "Durée MM" input)
*after* those cards in the JSX shifted what counted as "last" — the tests kept passing (or, for
ones with weak assertions like `toBeTruthy()` on static text, silently stopped exercising their
intended code path at all, dropping real coverage with no failing test to point at why — the
exact same failure shape as Problem 4 above, different mechanism).

**Rule:** never select an element by absolute position/count when the page can grow unrelated
siblings later. Scope with `within(container)` on the specific panel/modal being tested (most
robust — a sibling section's new buttons are structurally excluded), or an exact-text match on
the one you mean (`{ name: 'Ticker' }` instead of `{ name: /ticker/i }`, if another field's
label happens to contain the same substring — as happened here with "Ticker Pétrole"/"Ticker
Or"). When adding a new always-rendered element to a page that already has similarly-labeled
siblings, grep the test file for `getAllBy*`/`.slice(-N)`/`[N]`/`/regex/i` patterns that could
now match your new element, don't assume "my new tests pass" is sufficient.

**Problem 6 (issue #48): a `v8 ignore next` comment placed *mid-expression* isn't reliably
attached by Oxc's comment-to-AST mapping** (`git log --grep 'bump vite to 8.2.1'`) — between a
destructuring `=` and its multi-line RHS call, or inline before a JSX `{`-opened expression
continuing on the next line, even once the general upstream fix chain
([oxc-project/oxc#20549](https://github.com/oxc-project/oxc/issues/20549) → `oxc` 0.123.0 →
`rolldown` 1.0.0-rc.13 → `vite@8.0.8`) has shipped. **Fix: move the comment to be the immediate
leading line of the specific property/expression that contains the branch**, not before an
outer wrapper several tokens/lines away — e.g. `useSortable({ data, defaultCol: 'x', /* v8
ignore next -- @preserve */ getValue: (a, col) => ... })` with the comment directly above
`getValue`, not above the whole `useSortable(...)` call. If a future `v8 ignore next` addition
shows a branch/statement coverage gap that disappears when temporarily removing the surrounding
multi-line expression, check comment placement mid-expression first before assuming a new
upstream regression.

**Current CI thresholds:**
- statements: **100%** (unreachable code marked with `/* v8 ignore next -- @preserve */`)
- branches: **100%** (see Problem 2 above — the 94% figure was based on a misdiagnosis; the
  suite has since reached genuine 100% branch coverage)
- functions: **100%**
- lines: **100%**

**Test utility structure:**
Helpers live in `frontend/tests/utils/` (outside `src/`) to avoid polluting metrics.
Imports from tests: `'../../tests/utils/patternfly-mocks'` etc.

### React Query in tests
Always configure `makeWrapper()` with:
```ts
gcTime: 0, staleTime: Infinity, retry: false,
refetchOnWindowFocus: false, refetchOnMount: false, refetchOnReconnect: false
```
See `frontend/tests/utils/react-query-wrapper.tsx`.

## Frontend test performance — resolved issue

A 16-minute test hang was traced to `StalePriceWarning` (`DashboardPage.tsx`)'s infinite
re-render loop — see the root `CLAUDE.md`'s "React pattern to avoid — setState with
unmodified new array ref" section for the root cause and fix (commit 8ca41c2). Result: fast, clean exit.

### What does NOT work (do not retry)
- `vi.useFakeTimers()` in DashboardPage.test.tsx → breaks tests using `userEvent` (which requires real timers)
- Brute-force timer clearing (loop 0→max via `window.setTimeout()`) → OOM: jsdom accumulates millions of IDs, loop allocates 8GB+
- `pool: 'threads'` or `pool: 'vmThreads'` → same behavior, generic "forks worker" message
- `teardownTimeout: 5000` → applies to `afterAll/afterEach` hooks, not worker process timeout
- `globalSetup teardown()` → only called AFTER all workers finish
- `--forceExit` → does not exist as CLI flag in Vitest 4.x

### Expected noise: `act(...)` warnings across many page test files
`Warning: An update to <Component> inside a test was not wrapped in act(...)` appears in
several page test files — an async state update (React Query background refetch, a `useEffect`
timer) lands slightly outside React Testing Library's tracked `act()` boundary. Not a sign of
incorrect component behavior by itself, and the suite still passes with 100% coverage regardless.
Given the number of files involved and the varied async causes, this is deliberately left as
documented noise rather than chased down file-by-file for a purely cosmetic fix (see #8) — unlike
the `validateDOMNesting` warning that used to accompany it (fixed at the source: `patternfly-mocks.tsx`'s
`Thead`/`Tbody` mocks were bare passthrough fragments, so `<Tr>` landed directly under `<table>`
with no wrapping element — now real `<thead>`/`<tbody>` elements), there's no single shared root
cause here to fix.

**A second, distinct variant — `SettingField.test.tsx`'s "save flow > saves the edited value and
shows a transient confirmation"**: `The current testing environment is not configured to support
act(...)` (not the "update... was not wrapped in act" wording above — a different React warning,
about `IS_REACT_ACT_ENVIRONMENT` rather than a missed `act()` boundary). Root cause: that
`describe` block's `beforeEach` uses `vi.useFakeTimers({ shouldAdvanceTime: true })`, which lets
Vitest's fake clock auto-tick in the background against real wall-clock time (needed so
`userEvent.setup({ advanceTimers: vi.advanceTimersByTime })`'s own internal waits resolve during
`user.clear`/`user.type`/`user.click`) — `SettingField.tsx`'s own `setTimeout(() =>
setSaved(false), 2000)` can fire via that background auto-tick at a moment outside any `act()`
scope, racing the test's own explicit `await act(async () => { vi.advanceTimersByTime(2000); })`.
Confirmed pre-existing (reproduced identically on the commit before a round of dependency bumps,
in an isolated worktree) — not a regression from any specific package version. **Do not "fix" this
by dropping `shouldAdvanceTime: true`**: tried live, it fixes the warning but breaks both tests in
the block with a 5000ms timeout (`userEvent`'s internal waits stop resolving without it). Left as
documented noise for the same reason as the general case above — the real fix would need rewriting
how this test drives fake timers around `userEvent`, not a one-line tweak.

### i18n initialization in tests
`patternfly-mocks.tsx` imports `../../src/i18n` to ensure `initReactI18next` runs in each
test file's module context — required for `useTranslation()` to work without a provider.
Components that don't import patternfly-mocks must import `../../src/i18n` (or `./i18n`)
directly (e.g. `SyncBadge.test.tsx`, `RefreshBanner.test.tsx`).

### `@testing-library/jest-dom` must be imported per test file, not centralized in `setupFiles`
On Vitest 5 (migrated from 4.x), `import '@testing-library/jest-dom'` (the bare, Jest-oriented
entry point) no longer augments Vitest's `expect` at all — every `jest-dom` matcher call
(`toBeInTheDocument`, `toHaveValue`, etc.) fails with `Error: Invalid Chai property: ...`. Fix:
import the dedicated `import '@testing-library/jest-dom/vitest'` subpath instead, which targets
Vitest's actual `Assertion` type/runtime shape.

**This import must stay in every individual test file — moving it into the shared
`tests/utils/vitest-setup.ts` (`setupFiles`) does not work**, confirmed by directly reproducing
both ways: a per-file `import '@testing-library/jest-dom/vitest'` registers the matcher
correctly; the exact same import placed once in `vitest-setup.ts` does not reach the `expect`
instance each test file actually uses. Root cause not fully pinned down (Vitest 5's per-file
test isolation likely gives each file module its own `expect`, so a `setupFiles`-level
`expect.extend()` call doesn't propagate) — but the fix that empirically works is per-file
imports, same as before the migration, just with the corrected subpath.

