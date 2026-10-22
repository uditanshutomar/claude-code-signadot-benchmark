# Reference solutions and grader controls

These are inputs for checking the grader before run 1, not benchmark results. Each patch applies to HotROD commit
`b16178651580a8ba3ceb45ac7c59f4579611b0b3` on its own.

- `t1.patch`: Task 1 reference solution. It changes the Go JSON contract and updates the React consumers.
- `t2.patch`: Task 2 reference solution. It computes the fare in the driver notification, stores ride history in
  MySQL, adds the location endpoints and frontend proxy, and adds the React history table and fare display.
- `check08-fare-in-countdown-only.patch`: a Task 2 diff from a smoke run that shows the fare in the ETA countdown but
  not in the arrival message. This checks that the grader accepts the countdown-only fare display the prompt asks for.

| Control | Input | Expected |
| --- | --- | --- |
| check01 | Unmodified repository, Task 1 | FAIL |
| check02 | `t1.patch` | PASS |
| check03 | Unmodified repository, Task 2 | FAIL |
| check04 | `t2.patch` | PASS |
| check08 | `check08-fare-in-countdown-only.patch` | PASS |

Results, input hashes and the grader file hashes are in `../calibration.json`.

To rerun a control, create `runs/<id>/` with the patch as `submission.diff` (empty for an unmodified repository) and
`submission.json` set to `{"task": "t1", "base_sha": "b16178651580a8ba3ceb45ac7c59f4579611b0b3"}` (or `"t2"`), then
run `./grade.sh <id>`.
