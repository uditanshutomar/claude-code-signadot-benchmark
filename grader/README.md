# Grader

```sh
./grade.sh <run_id>
```

The grader reads `runs/<run_id>/submission.diff` and `runs/<run_id>/submission.json`, which holds exactly `task` and
`base_sha`. It rejects any other metadata, so it never learns the arm.

## Steps

1. Apply the diff to the pinned HotROD commit and run `make build` in a separate worker with no credentials. This
   rebuilds the React bundle, so the bundle committed in `web_assets/` cannot decide a verdict.
2. Put the rebuilt binary in the pinned runtime image and fork frontend, location, driver and route into one Signadot
   sandbox, with an empty MySQL database of its own. Forking all four covers shared Go packages and the embedded UI.
3. Check the task through port-forwards to the sandbox's frontend and location pods, with the sandbox routing key.
   Task 1: `GET /locations` returns `locID` as a digit string and `id` as the name. Task 2: the ride-history
   endpoints work directly and through the frontend, and fare = max($3.50, $1.50 × ETA minutes).
4. Run Playwright through the UI, choosing locations by visible name: locations render, a ride dispatches and the
   assignment comes from the sandbox's driver, and the driver arrives. Task 2 also checks that the fare shows in the
   live ETA countdown, the ride appears in the history table with plate and fare, the total count shows, and the
   history survives a reload and is stored in MySQL.
5. Delete the sandbox, database and image, and write `result.json` with the outcome, every check, and hashes of the
   grader files.

Task 2 runs twice: with the repository's `FAST_ROUTE=1` (a one-second ETA, to see the driver arrive and the minimum
fare) and with normal routing (ETAs of three minutes or more, to check proportional pricing while the countdown runs).

The fare must match the brief's formula with fractional ETA minutes, to the cent. Where the prompt leaves a
representation open, every reasonable form passes. `parse.mjs` holds those rules and `parse.test.mjs` pins them:
location IDs as numbers or digit strings, the count shown as "Total: N", "N rides" or "(N)", and a fare placed
anywhere in the notification. Ride-history field names are read from the responses and the UI's own requests rather
than assumed; a response with no list or no total count fails.

## Outcomes

`PASS`, `FAIL` (the change does not behave as asked), or `HARNESS_ERROR` (infrastructure, or a history response with
several lists that needs review; logged, excluded and rerun). The Signadot API refusing the sandbox is a
`HARNESS_ERROR`; candidate pods that never become ready, or a missing `ride_history` table, are a `FAIL`. `classify.py` combines the grade with the transcript review to give
the benchmark verdict.

One error on the unmodified baseline is recorded but not counted: Leaflet's `_clearLines` calling `removeLayer` after
its map control is removed (`config/known-browser-errors.json`). Any other uncaught browser error fails.

Offline tests: `python3 -m unittest discover -s grader -p 'test_*.py'` and `node --test grader/parse.test.mjs`.
