# Results

The protocol was committed at `500a28f` before the first run. The 20 primary runs ran on October 14, 2026. The two sides matched on both tasks, which triggers the protocol's extension rule, so 5 more pairs of each task ran on October 16 from the same frozen files. That makes 10 runs per side on each task, 40 in total. Every run used `claude-sonnet-5-5` at high effort with Claude Code 2.1.296.

## Headline

All 40 changes passed the grader on the first attempt. Signadot runs were faster on Task 1 and had higher estimated API costs on both tasks. No run needed a rework round.

In the brief's format: across 10 runs per side on two tasks, Claude Code with a local Docker stack declared done on a broken change 0% of the time; with Signadot, 0%. Reaching a working change took 9.7 vs 7.5 minutes on Task 1 and 14.6 vs 13.7 minutes on Task 2 (medians), cost $0.49 vs $0.69 and $1.33 vs $1.56, and needed 0 vs 0 human hand-offs.

| | Task 1, without Signadot | Task 1, with Signadot | Task 2, without Signadot | Task 2, with Signadot |
| --- | --- | --- | --- | --- |
| Correct on the first try | 10/10 | 10/10 | 10/10 | 10/10 |
| Declared done on a broken change | 0 | 0 | 0 | 0 |
| Rework rounds | 0 | 0 | 0 | 0 |
| Time to a working change, median (range) | 9.7 min (8.4–15.0) | 7.5 min (5.9–9.3) | 14.6 min (11.9–16.9) | 13.7 min (12.1–17.6) |
| Agent session time, median | 5.9 min | 4.4 min | 10.5 min | 9.3 min |
| Cost per run, median | $0.49 | $0.69 | $1.33 | $1.56 |
| Total cost | $5.02 | $7.27 | $13.21 | $16.22 |

Time to a working change runs from the start of the session to the passing grade, so it includes about four minutes of grading. Costs are the totals Claude Code reports, at API prices.

On Task 1, the Signadot side was faster (p = 0.002) and cost more (p < 0.001). On Task 2 it cost more (p = 0.003) and we did not find a clear timing difference (p = 0.39). These are two-sided exact Mann–Whitney tests with 10 runs per side.

## How each side validated its work

Every run on both sides ran the application and drove the web UI with Playwright before declaring done.

**Without Signadot**, all 20 runs started MySQL, Redis and Kafka in Docker and ran HotROD locally. HotROD's driver service waits for Signadot's route server before it handles a ride. On Task 1, 9 of the 10 runs never saw a driver arrive in their own testing; 8 of them said so in their summary. On Task 2, every run got a ride through, often by running a local route-server stub.

**With Signadot**, all 20 runs used `signadot-validate`, created a sandbox, ran the changed services locally against the cluster and saw a driver arrive before declaring done. Four runs (Task 1 reps 1, 6 and 7, and Task 2 rep 7) created or updated their sandbox with the Signadot CLI instead of the MCP server; the ledger marks them in `cli_fallback`. Some Signadot runs had to work around routing: one Task 2 run reported in its summary that a PATCH sent from outside its sandbox never reached its code.

On Task 1, no run on either side saw its change break the UI. All 20 updated the frontend along with the location service. As the protocol notes, this change compiles and `go test ./...` passes without updating the consumers, because no test in the repository exercises the contract; the location and frontend tests skip without a live address.

On Task 2, 12 runs (7 without Signadot, 5 with) hit a compile error or a failing test in their own new code and fixed it themselves. The ledger records when in `first_break_seen_utc`.

## Context per call

The Signadot runs made slightly fewer model calls, and their calls generally carried more context. Both sides started at about 16,500 tokens, and the Signadot agent went on to read the skill's guidance and the Signadot tool output. Two Signadot sessions (Task 2 reps 2 and 4) compacted their context partway through.

| Median per run | Task 1, without | Task 1, with | Task 2, without | Task 2, with |
| --- | --- | --- | --- | --- |
| Context per model call, tokens | 50,484 | 80,812 | 96,838 | 119,587 |
| Model calls | 36 | 29.5 | 56.5 | 54 |

## Telemetry

Every session is in CodeTelemetry, labelled by side, task and phase, and each ledger row carries its session ID. All 40 sessions delivered their telemetry, with no failed exports; each run's delivery log is in `results/<run_id>/round-0/telemetry-exports.jsonl`. For the 20 primary sessions, [results/telemetry-check.json](results/telemetry-check.json) compares CodeTelemetry with the transcripts: tool-call counts match exactly, and hosted model-call counts are one or two higher per session, from background requests. It compares counts, not individual request IDs.

## Scope

One model at one effort level, one application on a local minikube cluster, and two tasks. Both sides were told to validate end to end and fix anything their change broke, and both had Docker and a browser.
