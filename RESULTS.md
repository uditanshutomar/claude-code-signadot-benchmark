# Results

Protocol and source frozen at commit `500a28f978b4c8f67159b84a13c27d48974416a5` before run 1. The 20 primary runs ran
on 2026-10-14 UTC. The extension rule then called for 5 more pairs of each task, which ran on 2026-10-16 UTC from the
same frozen files: their freeze record cites commit `81d7a97`, whose frozen files are byte-identical to `500a28f`
(the only change between them adds the primary results). Every run used `claude-sonnet-5-5`, effort high, Claude
Code 2.1.296, in the pre-registered order. All 40 runs are in `ledger.csv`; per-run transcripts, diffs, grader
outputs and telemetry delivery logs are in `results/`.

## Headline

Across 10 runs per arm on two tasks, Claude Code without a real environment declared done on a broken change 0% of
the time; with Signadot, 0%. Reaching a working change took 9.7 vs 7.5 minutes on Task 1 and 14.6 vs 13.7 minutes on
Task 2 (medians), cost $0.49 vs $0.69 and $1.33 vs $1.56 (API-equivalent medians), and needed 0 vs 0 human hand-offs.

| | Task 1: contract change | | Task 2: cross-service feature | |
| --- | --- | --- | --- | --- |
| | **Arm A, no Signadot** | **Arm B, Signadot** | **Arm A, no Signadot** | **Arm B, Signadot** |
| Initial verdict `VERIFIED_CORRECT` | 10/10 | 10/10 | 10/10 | 10/10 |
| Declared done on a broken change | 0 | 0 | 0 | 0 |
| Rework rounds (human hand-offs) | 0 | 0 | 0 | 0 |
| Time to a working change, median (range), min | 9.7 (8.4–15.0) | 7.5 (5.9–9.3) | 14.6 (11.9–16.9) | 13.7 (12.1–17.6) |
| Agent session time, median, min | 5.9 | 4.4 | 10.5 | 9.3 |
| Cost to a working change, median, USD | 0.49 | 0.69 | 1.33 | 1.56 |
| Total cost, USD | 5.02 | 7.27 | 13.21 | 16.22 |

Time to a working change runs from the start of the session to the passing grade, so it includes about four minutes
of grading per run. Costs are Claude Code's reported `total_cost_usd` under a Claude subscription: API-equivalent
estimates, not invoices.

On Task 1, Arm B was faster (time to a working change, p = 0.002) and cost more (p < 0.001). On Task 2, Arm B cost
more (p = 0.003), but the time difference is within noise (p = 0.39). These are two-sided exact Mann–Whitney tests,
10 runs per arm.

## How each arm validated

Both arms were told to validate end to end, including the web UI, and every run drove the UI with Playwright.

- **Arm A** started MySQL, Redis and Kafka itself with Docker in all 20 runs and ran HotROD locally. The brief treats
  this as a legitimate strategy. HotROD's driver service waits for a Signadot route server before it handles a ride,
  and Arm A has none. On Task 1, 9 of the 10 Arm A runs never saw a driver arrive in their own testing: 8 said so in
  their closing summary, one did not mention it, and the tenth temporarily bypassed the driver's check. All ten
  declared done, and the grader found all ten changes correct. On Task 2, every Arm A run got a ride through, by
  working around the route server, for example with a throwaway fake one.
- **Arm B** invoked `signadot-validate` at the start of all 20 runs, created a sandbox on the cluster, ran the changed
  services locally against it, and saw a driver arrive in every run. Four runs (Task 1 reps 1, 6 and 7; Task 2 rep 7)
  created or updated their sandbox with the Signadot CLI rather than MCP (`cli_fallback`).

On Task 1, no agent in either arm ever observed its change breaking the UI: all 20 updated the frontend along with
the location service, and none hit a compile error or a failing test. As the brief anticipated, the change compiles
and `go test ./...` passes without updating the consumers, because no test in the repository exercises the contract;
the location and frontend tests skip without a live address. On Task 2, 12 runs (7 in Arm A, 5 in Arm B) hit a
compile error or a failing test in their own new code and fixed it themselves; `first_break_seen_utc` records when.

## Extension rule

After the primary runs the arms differed by 0 of 5 on both tasks, below the threshold of 4, so the rule called for 5
more pairs of each task. They ran with the same model, source and settings, and all 20 were `VERIFIED_CORRECT` on the
first attempt, with no harness errors. At 10 runs per arm the arms differ by 0 of 10 on both tasks.

## Telemetry

Every session is in CodeTelemetry, labelled by arm, task and phase. For the 20 primary sessions,
`results/telemetry-check.json` compares each session's hosted model and tool calls with its transcript: tool calls
match exactly in all 20, and no model call is missing (hosted counts include one or two background requests per
session). Across all 40 sessions the relay logged 0 undelivered exports.

## Scope

One model, one effort level, one application (HotROD) on a local minikube cluster, and two tasks. The shared prompt
told both arms to validate end to end and to fix anything their change broke, and both arms had Docker and a browser.
HotROD's driver depends on Signadot's route server, so a purely local setup cannot run a ride end to end without a
workaround; another application might not have that gap.
