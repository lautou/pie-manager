// SPDX-License-Identifier: AGPL-3.0-or-later

interface AxiosErrorLike {
  response?: { data?: { detail?: string } };
}

/**
 * Extracts a FastAPI `{detail: "..."}` message from an Axios rejection, falling back to
 * `fallback` when the error has no such shape (network error, non-Axios throw, etc.).
 */
export function extractApiErrorMessage(err: unknown, fallback: string): string {
  return (err as AxiosErrorLike)?.response?.data?.detail ?? fallback;
}
