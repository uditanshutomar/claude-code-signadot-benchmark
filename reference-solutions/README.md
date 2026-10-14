# Reference solutions and grader controls

These are inputs for checking the grader before run 1, not benchmark results. Each patch applies to HotROD commit
`b16178651580a8ba3ceb45ac7c59f4579611b0b3` on its own.

- `t1.patch`: hand-written Task 1 solution. It changes the Go JSON contract and updates the React consumers.
- `t2.patch`: hand-written Task 2 solution. It computes the fare in the driver notification, stores ride history in
  MySQL, adds the location endpoints and frontend proxy, and adds the React history table and fare display.
- `check08-fare-in-countdown-only.patch`: a Task 2 diff from a smoke run that shows the fare in the ETA countdown but
  not in the arrival message. The prompt asks only for the countdown, so it must pass.

| Control | Input | Expected |
| --- | --- | --- |
| check01 | Unmodified repository, Task 1 | FAIL |
| check02 | `t1.patch` | PASS |
| check03 | Unmodified repository, Task 2 | FAIL |
| check04 | `t2.patch` | PASS |
| check08 | `check08-fare-in-countdown-only.patch` | PASS |

Results, input hashes and the grader file hashes are in `../calibration.json`.
