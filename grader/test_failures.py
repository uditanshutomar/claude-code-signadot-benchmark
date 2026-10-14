import unittest
import grade


class FailureAttributionTests(unittest.TestCase):
    def test_control_plane_refusal_is_infrastructure(self):
        out = "Error: 403 Forbidden: can't upsert sandbox: can't go over limit (monthlySandboxes: 51/50)"
        self.assertEqual(grade.apply_failure(out), 'harness')
        self.assertEqual(grade.apply_failure('Error: 401 Unauthorized: unauthorized'), 'harness')
        self.assertEqual(grade.apply_failure('Error: 503 Service Unavailable'), 'harness')

    def test_sandbox_that_never_becomes_ready_is_the_candidate(self):
        self.assertEqual(grade.apply_failure('Error: sandbox "ctg-x" is not ready: location: CrashLoopBackOff'), 'candidate')

    def test_missing_history_table_is_the_candidate(self):
        out = "ERROR 1146 (42S02) at line 1: Table 'ctg_x.ride_history' doesn't exist"
        self.assertEqual(grade.history_count_failure(out), 'candidate')
        self.assertEqual(grade.history_count_failure('error: unable to upgrade connection: pod not found'), 'harness')


if __name__ == '__main__':
    unittest.main()
