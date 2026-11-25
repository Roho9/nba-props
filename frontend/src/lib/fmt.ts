export const pct = (x: number | null | undefined, d = 1) => (x == null ? "n/a" : `${(x * 100).toFixed(d)}%`);
export const am = (x: number | null | undefined) => (x == null ? "n/a" : x > 0 ? `+${x}` : `${x}`);
export const signed = (x: number | null | undefined, d = 3) => (x == null ? "n/a" : `${x >= 0 ? "+" : ""}${x.toFixed(d)}`);
export const num = (x: number | null | undefined, d = 1) => (x == null ? "n/a" : x.toFixed(d));

function asUTC(s: string) {
  return new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(s) ? s : s + "Z");
}
export const time = (s: string | null | undefined) =>
  s ? asUTC(s).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : "n/a";
export const dateTime = (s: string | null | undefined) =>
  s ? asUTC(s).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "n/a";
export const ago = (s: string | null | undefined) => {
  if (!s) return "never";
  const m = Math.round((Date.now() - asUTC(s).getTime()) / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  return h < 48 ? `${h} h ago` : `${Math.round(h / 24)} d ago`;
};
export const minutesSince = (s: string | null | undefined) => (s ? (Date.now() - asUTC(s).getTime()) / 60000 : Infinity);
