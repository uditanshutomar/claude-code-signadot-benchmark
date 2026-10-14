// Parsing rules shared by check.mjs. They accept every reasonable reading of the
// task text and nothing looser; parse.test.mjs pins each case.

// The dispatch may carry location IDs as numbers or as digit strings.
export const sameId = (value, expected) => value !== undefined && value !== null && String(value) === String(expected);

// HotROD's body is "Driver <plate> arriving in <eta>"; the fare may be inserted anywhere.
export const plateFrom = body => body.match(/Driver\s+([A-Za-z0-9-]+)/)?.[1];

// The brief's formula: max($3.50, $1.50 x ETA minutes), with fractional minutes, shown to the cent.
export function fareMatches(fare, seconds) {
  return Math.abs(fare - Math.max(3.5, 1.5 * seconds / 60)) < 0.011;
}

// "Total: 3", "Count: 3", "3 rides", "3 total" or "Ride History (3)".
export function showsTotal(text, total) {
  const n = String(total);
  return new RegExp(`(?:total(?:\\s+rides)?|count)\\s*[:(]?\\s*${n}\\b|\\b${n}\\s+(?:total\\s+)?rides?\\b|\\b${n}\\s+total\\b|\\(\\s*${n}\\s*\\)`, 'i').test(text);
}

// The live countdown ("... will arrive in 09:24"), where the prompt puts the fare; not the arrival message.
export const ETA_COUNTDOWN = /will arrive|arriv\w*\s+in\b/i;

// GET /ride-history must return a list and a total count; field names are the agent's choice.
// Returns {rows, total}, {missing} when the response lacks either, or {ambiguous} when it has several lists.
export function historyShape(value) {
  const arrays = [], counts = [];
  (function walk(x, key) {
    if (Array.isArray(x)) { arrays.push(x); return; }
    if (x && typeof x === 'object') { for (const [k, v] of Object.entries(x)) walk(v, k); return; }
    if (/total|count/i.test(key || '') && Number.isInteger(x)) counts.push(x);
  })(value);
  if (arrays.length > 1) return {ambiguous: 'several lists in the history response'};
  if (arrays.length === 0) return {missing: 'history response has no list of rides'};
  if (counts.length === 0) return {missing: 'history response has no total count'};
  return {rows: arrays[0], total: counts[0]};
}
