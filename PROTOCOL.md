# Protocol

This protocol, the harness, the grader and the prompts are committed before run 1. The report cites that commit.
Every run goes in `ledger.csv`, including harness errors and contaminated reruns. Nothing is dropped.

## Question

Given the same task and the same instructions, does Claude Code ship a working change more often when it has a
real environment to verify in, and what does it cost to reach a working change with and without one?

## Design

One variable: Signadot. Everything else is identical, instructions included.

|  | Arm A (control) | Arm B (Signadot) |
| --- | --- | --- |
| Tools | Claude Code, the HotROD repository, Playwright + Chromium + Playwright MCP, grpcurl | Same, plus the Signadot CLI, the Signadot MCP server, the `signadot-validate` skill and a connection to the cluster |
| Prompt | Task prompt + shared suffix | Same, plus one sentence naming the skill and the cluster |

Model, effort, Claude Code version, Signadot CLI version, permission mode, and the HotROD and agent-skills
commits are pinned in [`config/pins.json`](config/pins.json). One model and one effort level are used for every run.

### Environment

- HotROD at the pinned commit runs in a local minikube cluster, namespace `ctbench-hotrod`, with the Signadot
  operator installed. Runs and grading use it one session at a time; the only other workloads are an idle,
  unrelated HotROD in namespace `hotrod` and an idle Signadot job runner.
- Each run gets a fresh Docker Sandboxes (`sbx`) VM from one pinned template: 2 CPUs, 4 GB memory, sudo and Docker
  available. No Claude memory, sessions or caches carry over. Go modules and npm packages are prewarmed in both
  arms before the clock starts.
- Arm B mounts the pinned `signadot/agent-skills` read-only and runs `signadot local connect`; the clock starts
  only after `signadot local status` passes. Arm A has no Signadot tools, key or cluster connection.
- Before each run, every Signadot sandbox in the benchmark namespace is deleted (the skill reuses an existing
  sandbox for the same workload) and the `ride_history` table is dropped.

### Tasks

**Task 1, contract change** ([`prompts/t1-a.txt`](prompts/t1-a.txt)):

> Make the location service's response return the id field as a JSON string called locID instead of a number,
> and rename name to id.

It compiles and `go test ./...` passes, because no test in the repository exercises the contract; the location
and frontend tests skip without a live address. `location.Location` is shared by the location server, the
frontend's Go client and the React UI, so the rename breaks the UI. No backward-compatible version exists, so a
correct change must update the consumers.

**Task 2, cross-service feature** ([`prompts/t2-a.txt`](prompts/t2-a.txt)): Base Prompt 2 of
[`source-harness/prompts/HOTROD.md`](source-harness/prompts/HOTROD.md), verbatim. Fare estimate plus ride
history across the driver, location and frontend services, including a new MySQL table.

### Prompts

Both tasks in both arms end with the shared suffix:

> Validate your work end to end, including the web UI. If your change breaks anything else, fix it so the app
> still works.

Arm B adds one sentence:

> Use /signadot-validate on the minikube cluster (namespace ctbench-hotrod).

The namespace is named because the cluster also runs an unrelated HotROD in namespace `hotrod`; without it the
skill stops to ask which workload to use. The four prompt files are frozen with this commit.

## Two phases per run

1. **Initial:** fresh VM and session, `claude -p "<prompt>" --model <id> --permission-mode bypassPermissions
   --output-format stream-json --verbose`, until the agent stops, with a 60-minute cap.
2. **Rework**, for any run that isn't `VERIFIED_CORRECT`, in either arm, including a run that hit the cap:
   resume that session with only `CI failed on your change: <grader output>. Fix it.`, then re-grade. Up to 3
   rounds, each with a 60-minute cap; each round counts as one human hand-off. The grader output is the grade
   status, the failing check and error, the checks that passed, and build errors if the build failed. Host paths
   and grader internals are removed. If the session hit the cap, the feedback says so.

## Scoring

`grade.sh <run_id>` sees only an opaque run ID, the final diff and the task number, never the arm. It:

1. Applies the diff to the pinned HotROD commit and runs `make build`, which rebuilds the React bundle, so the
   stale bundle committed in `web_assets/` cannot decide a verdict.
2. Deploys the rebuilt image for the frontend, location, driver and route services into one Signadot sandbox,
   with its own empty MySQL database, and deletes the sandbox and database afterwards. All four are forked so
   that shared Go packages and the embedded UI are always covered.
3. Checks the task. Task 1: `GET /locations` returns `locID` as a digit string and `id` as the name. Task 2: the
   ride-history endpoints behave as the prompt specifies, and fare = max($3.50, $1.50 × ETA minutes).
4. Runs Playwright through the UI, choosing locations by visible name: locations render, a ride dispatches, a
   driver arrives. For Task 2, the fare shows in the ETA and the ride appears in history with plate and fare.

The fare must follow the brief's formula with fractional ETA minutes, to the cent. Where the prompt leaves a
representation open, every reasonable form passes: location IDs in the dispatch as numbers or digit strings, the
fare anywhere in the notification, the total count shown as "Total: N", "N rides" or "(N)", and any field names for
ride history. A history response with no list or no total count fails; one with several lists is a `HARNESS_ERROR`
for review. These rules are pinned by `grader/parse.test.mjs`. An existing Leaflet error on
the unmodified baseline (`config/known-browser-errors.json`) is recorded but not counted; any other uncaught
browser error fails.

Failures are attributed as follows. The Signadot API refusing the grading sandbox (authentication, quota, outage)
is a `HARNESS_ERROR`; a sandbox whose candidate pods never become ready, or a missing `ride_history` table, is a
`FAIL`. A round that is already a `HARNESS_ERROR` is not graded.

Before run 1 the grader is checked: the unmodified repository fails both tasks and a hand-written reference
solution (`reference-solutions/`) passes both. One more control, a smoke-run diff that shows the fare only in the
ETA countdown, must pass. Results, with the grader file hashes, are in `calibration.json`.

| Verdict | Meaning |
| --- | --- |
| `VERIFIED_CORRECT` | Grader passes |
| `BROKEN_UNDETECTED` | Agent declared done; grader fails |
| `BROKEN_DETECTED_UNFIXED` | Agent reported a break it didn't fix; grader fails |
| `TASK_NOT_DONE` | The requested change isn't there, e.g. reverted to make the UI work |
| `DID_NOT_FINISH` | Hit the 60-minute cap |
| `HARNESS_ERROR` | Infrastructure failure, not an agent outcome. Logged, excluded, rerun |

The initial verdict and the verdict after rework are recorded separately. Verdicts that depend on what the agent
said (declared done, reported a break), and `skill_invoked`, `cli_fallback`, `services_touched` and
`first_break_seen_utc`, come from a transcript review that cites transcript line numbers (`scripts/annotate.py`).

## Run rules

1. Model, effort, Claude Code version, Signadot CLI version, permission mode, and the HotROD and agent-skills
   commits are pinned and recorded on every ledger row.
2. This protocol, the harness, the grader and the prompts are committed before run 1.
3. Runs are sequential and alternate A, B, A, B within each task, Task 1 first. Sessions never run concurrently.
4. Every primary run gets a fresh VM and session. Rework rounds are the only resumes.
5. Extension rule: if the arms differ by fewer than 4 of 5 in initial `VERIFIED_CORRECT` on a task, run 5 more
   pairs of that task.

## Contamination and harness errors

- Arm A building its own environment (for example `hotrod all` with locally started MySQL, Redis and Kafka) is a
  legitimate strategy and is recorded.
- Arm A using Signadot is contamination. The attempt stays in the ledger with `contaminated` in its notes, and a
  rerun with the same repetition number replaces it in every count.
- A run that ends on a question to the user is a prompt or harness bug. It is fixed in the smoke tests, never
  mid-benchmark.

## Measurements

- **Cost** is Claude Code's reported `total_cost_usd`. Runs use a Claude subscription, so it is an
  API-equivalent estimate, not an invoice. A resumed session reports cumulative totals, so each rework round's
  cost is the difference from the previous round.
- **Time to a working change** runs from the start of the initial session to the passing grade, including rework
  and grading.
- **Hand-offs** are rework rounds.

### Capacity

The Signadot org allows 50 new sandboxes a month; each grade creates one, and each Arm B run creates its own. If
the quota runs out, the affected run is a `HARNESS_ERROR`, and runs pause until the monthly reset, then resume with
the same model, source and settings.

### Telemetry

Every session exports OpenTelemetry to CodeTelemetry, set in the VM's `~/.claude/settings.json`:

```
CLAUDE_CODE_ENABLE_TELEMETRY=1
CLAUDE_CODE_ENHANCED_TELEMETRY_BETA=1
OTEL_METRICS_EXPORTER=otlp  OTEL_LOGS_EXPORTER=otlp  OTEL_TRACES_EXPORTER=otlp
OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:14318   # scripts/otlp-relay.py, forwarding to https://ingest.codetelemetry.com
OTEL_LOG_USER_PROMPTS=1  OTEL_LOG_ASSISTANT_RESPONSES=1  OTEL_LOG_TOOL_DETAILS=1  OTEL_LOG_TOOL_CONTENT=1
OTEL_METRICS_INCLUDE_SESSION_ID=true
OTEL_RESOURCE_ATTRIBUTES=deployment.environment=ctbench-arm-<a|b>,env=ctbench-arm-<a|b>,ctbench.task=<t1|t2>,ctbench.phase=<initial|rework>
OTEL_BSP_MAX_EXPORT_BATCH_SIZE=4  OTEL_BLRP_MAX_EXPORT_BATCH_SIZE=8
OTEL_EXPORTER_OTLP_TIMEOUT=30000  OTEL_BLRP_EXPORT_TIMEOUT=60000  OTEL_BSP_EXPORT_TIMEOUT=60000
CLAUDE_CODE_OTEL_SHUTDOWN_TIMEOUT_MS=120000  OTEL_METRIC_EXPORT_INTERVAL=30000  OTEL_METRIC_EXPORT_TIMEOUT=30000
```

Claude Code's direct HTTPS export through the VM's egress proxy lost whole batches (a tool-heavy test session
arrived with 0 of 25 tool calls). So each VM runs `scripts/otlp-relay.py` on 127.0.0.1 port 14318 (not the standard
4318, where HotROD itself exports its traces when an agent runs it locally): Claude Code exports to it over plain
HTTP, and it forwards every request unchanged to CodeTelemetry, retrying failures, and logs each export's HTTP
status to the round's `telemetry-exports.jsonl`. Requests without the ingest key come from other processes; the
relay refuses them and logs them as `foreign`. A round whose log shows no exports, or any of Claude Code's exports
not delivered, is a `HARNESS_ERROR`: logged, excluded and rerun. Before the relay stops, it finishes every export
in flight. After collection, each session's model calls and tool calls in CodeTelemetry are compared with its
transcript. Through the relay the same test session, and a Task 2 smoke run, arrived complete. The last three lines
only keep each request small and stop a stalled export from blocking the queue. `env` repeats the arm because
CodeTelemetry's session view reads that key. Runs join the ledger by `session.id`.

## Ledger

`ledger.csv`, one row per run:

```
run_id, task, arm, rep, started_utc, ended_utc, duration_ms, cost_usd, num_turns,
model, effort, claude_code_version, permission_mode, hotrod_sha, skills_sha, session_id,
declared_done, initial_verdict, rework_rounds, rework_duration_ms, rework_cost_usd,
final_verdict, skill_invoked, cli_fallback, services_touched, first_break_seen_utc, notes
```

Each run's directory under `results/` holds, for every round, the prompt, the full transcript (`stream-json`), the
diff, the grader output and the telemetry delivery log, with credentials removed.
