# Results: primary runs

Protocol and source frozen at commit `500a28f978b4c8f67159b84a13c27d48974416a5` before run 1. Runs on 2026-10-14 UTC,
in the pre-registered order, with `claude-sonnet-5-5`, effort high, Claude Code 2.1.296. All 20 primary runs are in
`ledger.csv`; per-run transcripts, diffs, grader outputs and telemetry delivery logs are in `results/`.

## Headline

Across 5 runs per arm on two tasks, Claude Code without a real environment declared done on a broken change 0% of the
time; with Signadot, 0%. Reaching a working change took 9.6 vs 8.3 minutes on Task 1 and 15.9 vs 14.0 minutes on
Task 2 (medians), cost $0.43 vs $0.74 and $1.39 vs $1.69 (API-equivalent medians), and needed 0 vs 0 human hand-offs.

| | Task 1: contract change | | Task 2: cross-service feature | |
| --- | --- | --- | --- | --- |
| | **Arm A, no Signadot** | **Arm B, Signadot** | **Arm A, no Signadot** | **Arm B, Signadot** |
| Initial verdict `VERIFIED_CORRECT` | 5/5 | 5/5 | 5/5 | 5/5 |
| Declared done on a broken change | 0 | 0 | 0 | 0 |
| Rework rounds (human hand-offs) | 0 | 0 | 0 | 0 |
| Time to a working change, median (range), min | 9.6 (8.6–10.1) | 8.3 (7.4–9.3) | 15.9 (13.5–16.9) | 14.0 (12.1–17.6) |
| Agent session time, median, min | 5.8 | 4.7 | 11.8 | 9.3 |
| Cost to a working change, median, USD | 0.43 | 0.74 | 1.39 | 1.69 |
| Total cost, USD | 2.30 | 3.58 | 6.67 | 8.42 |

Time to a working change runs from the start of the session to the passing grade, so it includes about four minutes
of grading per run. Costs are Claude Code's reported `total_cost_usd` under a Claude subscription: API-equivalent
estimates, not invoices.

## How each arm validated

Every run in both arms tested the change end to end, including the web UI, as the shared prompt asked:

- **Arm A** started MySQL, Redis and Kafka itself with Docker in all 10 runs, ran HotROD locally and drove the UI with
  Playwright. The brief treats this as a legitimate strategy; Arm A was not unable to test.
- **Arm B** invoked `signadot-validate` in all 10 runs (within its first seven transcript lines), created a sandbox on
  the cluster, ran the changed services locally against it and drove the UI with Playwright. One run (Task 1, rep 1)
  used the Signadot CLI rather than MCP to update its sandbox.

On Task 1, no agent in either arm ever observed its change breaking the UI: all 10 updated the frontend's Go client and
React consumers before running anything. As the brief anticipated, the change compiles and `go test ./...` passes
without updating the consumers, because no test in the repository exercises the contract; the location and frontend
tests skip without a live address. On Task 2, five runs (three in Arm A, two in Arm B) hit a compile error or failing
test in their own new code and fixed it themselves; `first_break_seen_utc` records when.

## Extension rule

The arms differ by 0 of 5 on both tasks, below the threshold of 4, so the rule calls for 5 more pairs of each task.
These have not run yet: the Signadot organization's free plan allows 50 new sandboxes a month. They will run with the
same model, source and settings, and their rows will be added to the ledger.

## Telemetry

Every session is in CodeTelemetry, labelled by arm, task and phase. `results/telemetry-check.json` compares each
session's hosted model and tool calls with its transcript: tool calls match exactly in all 20, and no model call is
missing (hosted counts include one or two background requests per session). The relay logged 0 undelivered exports.

## Scope

One model, one effort level, one application (HotROD) on a local minikube cluster, and two tasks. The shared prompt
told both arms to validate end to end and to fix anything their change broke, and both arms had Docker and a browser.
