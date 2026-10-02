export function uiError(cause: unknown, english: string, chinese: string): string {
  const summary = `${english}（${chinese}）`
  return cause instanceof Error && cause.message ? `${summary}: ${cause.message}` : summary
}
