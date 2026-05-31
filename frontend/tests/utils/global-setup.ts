/**
 * Vitest global setup — kept as documentation only.
 * The actual hang fix is via `timeout` in package.json scripts.
 * See CLAUDE.md section "Performance des tests frontend" for full context.
 */
export function teardown() {
  // teardown() is called AFTER all fork workers have exited.
  // With DashboardPage's lingering handles, this never runs.
  // The actual fix is `timeout 120` in package.json test script.
}
