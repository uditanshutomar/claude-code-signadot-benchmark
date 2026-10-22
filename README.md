# Claude Code with and without Signadot

This repository holds a benchmark that compares Claude Code working on the same HotROD tasks with and without [Signadot](https://www.signadot.com/). Each run is headless, starts from a clean worker, and is graded by a script that never sees which side produced the change. Every run is here: its transcript, final diff, grader output and a row in the ledger.

The protocol was committed before the first run, at `500a28f`. [PROTOCOL.md](PROTOCOL.md) describes it in full.

## Results

| | Task 1, without Signadot | Task 1, with Signadot | Task 2, without Signadot | Task 2, with Signadot |
| --- | --- | --- | --- | --- |
| Correct on the first try | 10/10 | 10/10 | 10/10 | 10/10 |
| Time to a working change, median | 9.7 min | 7.5 min | 14.6 min | 13.7 min |
| Cost per run, median | $0.49 | $0.69 | $1.33 | $1.56 |
| Human hand-offs | 0 | 0 | 0 | 0 |

- All 40 changes passed the grader. No run declared done on a broken change.
- On Task 1, the Signadot runs reached a verified change faster. We did not find a clear Task 2 timing difference.
- On Task 1, 9 of the 10 runs without Signadot never saw a ride complete in their own testing, because HotROD's driver waits for Signadot's route server. Every Signadot run saw one complete.
- The Signadot runs cost more, and their model calls generally carried more context.

[RESULTS.md](RESULTS.md) has the full numbers and how each side validated its work.

## The tasks

Both sides get the same prompt. The Signadot side gets one extra sentence that names the skill and the cluster. The prompts are in [prompts/](prompts/).

- **Task 1, a contract change.** Make the location service return its id as a JSON string called `locID` and rename `name` to `id`. The change compiles, and `go test ./...` passes without updating the consumers, because no test in the repository exercises the contract. The location and frontend tests skip without a live address.
- **Task 2, a feature.** Add a fare estimate and ride history across the driver, location and frontend services, with a new MySQL table.

Every prompt ends with the same instruction: "Validate your work end to end, including the web UI. If your change breaks anything else, fix it so the app still works."

## How a run works

`./run-one.sh <task> <arm> <rep> --mode primary --execute` runs one session from start to finish. Without `--execute` it prints the plan and stops.

1. It creates a fresh Docker Sandboxes worker, resets HotROD to the pinned commit, drops the `ride_history` table and deletes any Signadot sandboxes left from the previous run.
2. On the Signadot side, it starts `signadot local connect` and waits until `signadot local status` passes.
3. It runs `claude -p` with the pinned model and effort, a 60-minute limit and `stream-json` output, then saves the transcript and the final diff.
4. It hands the diff to the grader. If the change fails, it resumes the same session with only the grader's output and grades again, up to three times.

Every session sends its telemetry to CodeTelemetry, labelled with the side, the task and the phase, so sessions can be grouped and compared there.

## How grading works

`./grade.sh <run_id>` sees only an opaque run ID and the diff. It never learns which side made the change.

It builds the diff at the pinned HotROD commit, deploys the result into a Signadot sandbox with its own database, and checks the task through the API. Then it drives the web UI with Playwright: it picks locations by name, dispatches a ride and waits for the driver to arrive. For Task 2 it also checks the fare in the countdown and the ride in the history table.

Before the first run, the grader failed the unmodified app on both tasks and passed a reference solution for each. Those checks are in [calibration.json](calibration.json), and the solutions are in [reference-solutions/](reference-solutions/). [grader/README.md](grader/README.md) covers the details.

## What's in this repository

| Path | Contents |
| --- | --- |
| [PROTOCOL.md](PROTOCOL.md) | The protocol, as committed before the first run |
| [RESULTS.md](RESULTS.md) | Results and how each side validated its work |
| [ledger.csv](ledger.csv) | One row per run, with the columns the protocol defines |
| [results/](results/) | Each run's transcript, final diff, grader output and telemetry delivery log |
| [prompts/](prompts/) | The four prompts: two tasks, two sides |
| `run-one.sh`, [scripts/](scripts/) | The headless runner: worker setup and reset, one run with its rework rounds, transcript review and export |
| `grade.sh`, [grader/](grader/) | The grader and its tests |
| [reference-solutions/](reference-solutions/) | Reference solutions used to check the grader |
| [calibration.json](calibration.json) | The grader check from before the first run |
| [config/](config/) | Pinned versions, model settings and the HotROD overlay |
| [source-harness/](source-harness/) | The interactive harness from [signadot/examples](https://github.com/signadot/examples/tree/main/closed-loop-comparison) that this one builds on |

## Run it yourself

These steps reproduce the original setup on an Apple-silicon Mac, with Linux ARM64 workers. The worker reset, the grader's build and the worker's Chromium path assume ARM64, so other hardware needs changes in `scripts/reset_worker.py`, `grader/grade.py` and `scripts/configure-worker.sh`. Values in angle brackets below are ones you record.

### Prerequisites

- Docker Desktop with Docker Sandboxes (`sbx` 0.48.0, logged in)
- minikube with the docker driver, kubectl and Helm
- Node 22, Python 3.11 or later, and git
- The [Signadot CLI](https://www.signadot.com/docs/getting-started/installation/signadot-cli) 1.8.0
- A Signadot account with an API key and a cluster token
- A Claude subscription, and a CodeTelemetry ingest key

### Set up HotROD and the cluster

Build HotROD at the pinned commit and load the image into minikube:

```bash
git clone https://github.com/signadot/hotrod work/hotrod
git -C work/hotrod checkout b16178651580a8ba3ceb45ac7c59f4579611b0b3
make -C work/hotrod build GOOS=linux GOARCH=arm64
docker build -t ctbench-hotrod:b16178651580 work/hotrod
minikube image load ctbench-hotrod:b16178651580
```

Deploy it into its own namespace:

```bash
kubectl --context minikube create namespace ctbench-hotrod
kubectl --context minikube apply -k config/hotrod
```

Install the Signadot operator with the `signadot/operator` Helm chart, version 1.4.0, with your cluster token in the secret `signadot/cluster-token` under the key `token`. Register the cluster as `minikube`, and set `signadot_org` in `config/pins.json`.

### Build the workers

Download `signadot-cli_mcp_linux_arm64.tar.gz` and `checksums.txt` from the [Signadot CLI v1.8.0 release](https://github.com/signadot/cli/releases/tag/v1.8.0) into `artifacts/downloads/`, and check the archive against `signadot_linux_arm64_archive_sha256` in `config/pins.json`.

Create the worker template:

```bash
sbx create --name ctbench-setup-a --skills off \
  --deny-network codetelemetry.com:443 --deny-network '**.codetelemetry.com:443' \
  claude <empty directory>
sbx exec -i ctbench-setup-a bash -s < scripts/prepare-worker.sh
sbx template save ctbench-setup-a ctbench-common:20261013
```

Create the two grader workers from it. Telemetry stays blocked on both, and the setup check below fails if it is not. The build worker has no credentials:

```bash
sbx create --name ctbench-grader-build --template ctbench-common:20261013 --skills off \
  --deny-network codetelemetry.com:443 --deny-network '**.codetelemetry.com:443' \
  claude work/grading-source
sbx create --name ctbench-setup-b --template ctbench-common:20261013 --skills off \
  --deny-network codetelemetry.com:443 --deny-network '**.codetelemetry.com:443' \
  claude work/worker-b
```

In `ctbench-setup-b`, extract the Signadot CLI into `/usr/local/bin` and write `~/.signadot/config.yaml` with your `org` and `api_key`. Then connect it to the cluster:

```bash
scripts/start-setup-worker.sh b
```

When setup is done, stop the setup workers. The runner refuses to reset shared data while any `ctbench-` worker is running, and the grader starts the ones it needs:

```bash
sbx stop ctbench-setup-a ctbench-setup-b ctbench-grader-build
```

Clone the agent skills at the pinned commit, and install the browser the grader uses:

```bash
git clone https://github.com/signadot/agent-skills ~/src/agent-skills
git -C ~/src/agent-skills checkout 3d7eee83830dd66a45cf80f7d85f8d9dd1c8f83b
npm ci --prefix tools
npx --prefix tools playwright install chromium
```

### Add your credentials

Create these files with mode `0600`. They are ignored by git:

- `private/claude-subscription.env`, containing `CLAUDE_CODE_OAUTH_TOKEN=<token>`
- `private/codetelemetry-ingest-key`
- `private/signadot-api-key`

### Freeze the protocol and run

Before the benchmark runs, do one smoke run of each task on each side. Approve it the same way as a benchmark run (below), with `"mode": "telemetry-smoke"`, and start it with `./run-one.sh t1 a 1 --mode telemetry-smoke --execute`. Each smoke run writes `runs/<id>/run.json`.

Use the smoke runs to confirm two things before you freeze. First, that every tool call and model call of a smoke session appears in CodeTelemetry. Second, that a resumed session's reported cost includes the first round, which is why the runner records rework cost as the difference between rounds. Set `telemetry_delivery_verified` and `cost_resume_reconciled` to `true` only once you have checked them.

Commit your setup, then record the freeze in `private/protocol-freeze.json`. `source_hashes` is the dictionary that `source_hashes()` in `scripts/protocol.py` returns, and `smoke_evidence` points at the four smoke runs. The runner refuses to start if the frozen files have changed since that commit:

```json
{"commit": "<git rev-parse HEAD>", "source_hashes": {"<path>": "<sha256>", "...": "..."},
 "approved": true, "cost_resume_reconciled": true, "telemetry_delivery_verified": true,
 "smoke_evidence": {"t1-a": "runs/<id>/run.json", "t1-b": "runs/<id>/run.json",
                    "t2-a": "runs/<id>/run.json", "t2-b": "runs/<id>/run.json"}}
```

Print the run order, which alternates the two sides within each task, Task 1 first:

```bash
python3 scripts/run-order.py
```

For each entry, approve that one run in `private/model-run-approval.json`, for example `{"mode": "primary", "task": "t1", "arm": "a", "rep": 1, "approved": true}`, and start it:

```bash
./run-one.sh t1 a 1 --mode primary --execute
```

Without `--execute`, the runner prints its plan and stops.

### Review and export

Review each transcript and record what you found in a small JSON file, one entry per round, with line references as evidence:

```json
{"0": {"task_present": true, "declared_done": true, "reported_unfixed_break": false,
       "skill_invoked": true, "cli_fallback": false, "services_touched": ["frontend", "location"],
       "first_break_seen_utc": "",
       "evidence": "round-0/transcript.jsonl:255 closing summary; round-0/transcript.jsonl:5 Skill signadot-validate"}}
```

Apply it to the run and its ledger row:

```bash
python3 scripts/annotate.py <run_id> <observations.json>
```

Then export the runs. The export removes the credentials it knows about, GitHub tokens, and your home directory from paths:

```bash
python3 scripts/export_results.py
```

It cannot recognise every kind of secret, so search `results/` yourself before you commit it.

## Check the code

```bash
python3 -m unittest discover -s grader -p 'test_*.py'
(cd scripts && python3 -m unittest discover -p 'test_*.py')
node --test grader/parse.test.mjs
python3 scripts/verify-preparation.py
```
