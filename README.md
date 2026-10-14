# Claude Code with and without a real environment

A headless, repeated, blind-graded comparison of Claude Code completing the same HotROD tasks with and without
[Signadot](https://www.signadot.com/) sandboxes to verify in. The method is in [PROTOCOL.md](PROTOCOL.md).

## Contents

| Path | What it is |
| --- | --- |
| `PROTOCOL.md` | The pre-registered protocol |
| `RESULTS.md` | Results of the primary runs |
| `prompts/` | The four frozen prompts: `t1`/`t2` × arm `a`/`b` |
| `run-one.sh`, `scripts/` | The harness: worker setup and reset, one run with up to three rework rounds, transcript annotation |
| `grade.sh`, `grader/` | The blind grader and its offline tests |
| `reference-solutions/` | Hand-written solutions used to check the grader |
| `calibration.json` | The grader check before run 1: baselines fail, references pass, with the grader file hashes |
| `config/` | Pinned versions, model settings, the HotROD overlay and the one known baseline browser error |
| `source-harness/` | The original interactive harness from [`signadot/examples`](https://github.com/signadot/examples/tree/main/closed-loop-comparison) this one is built from |
| `ledger.csv` | One row per run, failures and harness errors included |
| `results/` | Per-run transcripts (`stream-json`), final diffs and grader output |

## Running it

The original runs used an Apple-silicon Mac. Workers are Linux ARM64 Docker Sandboxes VMs; on other hardware, use
the matching CLI archive and record your own image and template IDs in `config/pins.json`. IDs below in angle
brackets are values you record, not values to copy.

**Host prerequisites:** Docker Desktop with Docker Sandboxes (`sbx` 0.48.0, logged in), minikube with the docker
driver, kubectl, Helm, Node 22, Python 3.11+, git, and the Signadot CLI 1.8.0. A Signadot org with an API key and a
cluster token, a Claude subscription, and a CodeTelemetry ingest key.

1. **HotROD.** `git clone https://github.com/signadot/hotrod work/hotrod`, check out `hotrod_sha` from
   `config/pins.json`, run `make build GOOS=linux GOARCH=arm64` there, then
   `docker build -t ctbench-hotrod:b16178651580 work/hotrod` and `minikube image load ctbench-hotrod:b16178651580`.
   Record the image ID from `docker image inspect` as `hotrod_image_id`.
2. **Cluster.** `kubectl --context minikube create namespace ctbench-hotrod`, then
   `kubectl --context minikube apply -k config/hotrod`. Install the Signadot operator with Helm chart
   `signadot/operator` 1.4.0 and your cluster token in secret `signadot/cluster-token` (key `token`). Register the
   cluster as `minikube` and set `signadot_org` in `config/pins.json`.
3. **Signadot CLI for the workers.** Download `signadot-cli_mcp_linux_arm64.tar.gz` and `checksums.txt` from the
   [`signadot/cli` v1.8.0 release](https://github.com/signadot/cli/releases/tag/v1.8.0) into `artifacts/downloads/`
   and check the SHA-256 against `signadot_linux_arm64_archive_sha256`.
4. **Worker template.** `sbx create --name ctbench-setup-a --skills off claude <empty dir>`, run
   `sbx exec -i ctbench-setup-a bash -s < scripts/prepare-worker.sh`, then
   `sbx template save ctbench-setup-a ctbench-common:20261013`. Record the template's short ID from
   `sbx template ls` as `common_worker_template_short_id`.
5. **Grader workers**, from that template:
   - `sbx create --name ctbench-grader-build --template ctbench-common:20261013 --skills off claude work/grading-source`
     (no credentials; it builds each diff).
   - `sbx create --name ctbench-setup-b --template ctbench-common:20261013 --skills off claude work/worker-b`,
     extract the CLI archive into its `/usr/local/bin`, and write `~/.signadot/config.yaml` there with `org:` and
     `api_key:`. `scripts/start-setup-worker.sh b` then connects it through `scripts/local-tunnel.py` and checks the
     baseline.
6. **Agent skills.** `git clone https://github.com/signadot/agent-skills ~/src/agent-skills` and check out
   `agent-skills_sha`.
7. **Host browser for the grader.** `npm ci --prefix tools` and `npx --prefix tools playwright install chromium`.
8. **Private files** (mode 0600, never committed): `private/claude-subscription.env` containing
   `CLAUDE_CODE_OAUTH_TOKEN=<token>`, `private/codetelemetry-ingest-key`, and `private/signadot-api-key`.
9. **Freeze.** Commit, then write `private/protocol-freeze.json`:

   ```json
   {"commit": "<git rev-parse HEAD>", "source_hashes": "<output of scripts/protocol.py source_hashes()>",
    "approved": true, "cost_resume_reconciled": true, "telemetry_delivery_verified": true,
    "smoke_evidence": {"t1-a": "runs/<id>/run.json", "t1-b": "runs/<id>/run.json",
                       "t2-a": "runs/<id>/run.json", "t2-b": "runs/<id>/run.json"}}
   ```

10. **Run.** `python3 scripts/run-order.py` prints the order. For each entry, write the one-use approval
    `private/model-run-approval.json` as `{"mode": "primary", "task": "t1", "arm": "a", "rep": 1, "approved": true}`
    and run `./run-one.sh t1 a 1 --mode primary --execute`. Without `--execute` it only prints the plan.
11. **Review and publish.** Annotate each run with `scripts/annotate.py` (transcript observations with line
    citations), then `python3 scripts/export_results.py` writes `results/` with credentials and home paths removed.
    Review `results/` before committing it.

`./grade.sh <run_id>` grades a diff on its own. Offline checks: `python3 -m unittest discover -s grader -p 'test_*.py'`,
`(cd scripts && python3 -m unittest discover -p 'test_*.py')`, `node --test grader/parse.test.mjs` and
`python3 scripts/verify-preparation.py`.
