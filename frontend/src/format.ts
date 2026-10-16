/** Keep short training runs legible while retaining compact large-run labels. */
export function formatIterations(value: number): string {
  if (Math.abs(value) < 1000) return String(Math.round(value));
  return `${Number((value / 1000).toFixed(1))}k`;
}
