// Offline checks for the parsing rules in parse.mjs: node --test grader/parse.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import {sameId, plateFrom, fareMatches, showsTotal, ETA_COUNTDOWN, historyShape} from './parse.mjs';

test('location identities match as numbers or digit strings', () => {
  assert.ok(sameId(1, 1));
  assert.ok(sameId('1', 1));
  assert.ok(sameId('123', 123));
  assert.ok(!sameId(2, 1));
  assert.ok(!sameId(undefined, 1));
});

test('plate is read even when the fare sits next to it', () => {
  assert.equal(plateFrom('Driver T757183C arriving in 1s'), 'T757183C');
  assert.equal(plateFrom('Driver T757183C (fare $3.50) arriving in 1s'), 'T757183C');
  assert.equal(plateFrom('Driver T757183C, fare $3.50, arriving in 1s'), 'T757183C');
  assert.equal(plateFrom('No driver here'), undefined);
});

test('total count is found in common display forms only', () => {
  for (const text of ['Total rides: 3', 'Total: 3', 'Count: 3', 'Ride History (3)', '3 rides', '3 total rides', '3 total'])
    assert.ok(showsTotal(text, 3), text);
  assert.ok(!showsTotal('Total: 13', 3));
  assert.ok(!showsTotal('Ride History\nMy Home 3:45 PM', 3));
});

test('ETA countdown text is recognised and the arrival message is not', () => {
  for (const text of ['The driver Angelo (T772642C) will arrive in 09:24 · Fare: $14.10', 'Arriving in 09:24, fare $14.10'])
    assert.ok(ETA_COUNTDOWN.test(text), text);
  assert.ok(!ETA_COUNTDOWN.test('Angelo Block V arrived'));
});

test('fare follows the brief exactly: max(3.50, 1.50 x fractional ETA minutes), to the cent', () => {
  const seconds = 253; // 4.2167 minutes -> 6.325
  assert.ok(fareMatches(6.33, seconds));
  assert.ok(fareMatches(6.32, seconds));
  assert.ok(!fareMatches(7.5, seconds));  // minutes rounded up
  assert.ok(!fareMatches(6, seconds));    // minutes rounded or truncated
  assert.ok(!fareMatches(3.5, seconds));
  assert.ok(fareMatches(3.5, 1));
});

test('history shape: a missing count or list fails, an ambiguous shape needs review', () => {
  assert.deepEqual(historyShape({rides: [{id: 1}], total: 1}), {rows: [{id: 1}], total: 1});
  assert.deepEqual(historyShape({data: {items: [], count: 0}}), {rows: [], total: 0});
  assert.ok(historyShape([{id: 1}]).missing);            // no total count
  assert.ok(historyShape({total: 3}).missing);            // no list
  assert.ok(historyShape({a: [], b: [], total: 0}).ambiguous);
});
