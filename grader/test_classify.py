import unittest
from classify import classify

class ClassificationTests(unittest.TestCase):
    def test_infrastructure_is_not_an_agent_failure(self):
        self.assertEqual(classify('HARNESS_ERROR', timed_out=True, declared_done=True), 'HARNESS_ERROR')
    def test_timeout_is_retained_even_if_partial_change_passes(self):
        self.assertEqual(classify('PASS', timed_out=True), 'DID_NOT_FINISH')
    def test_baseline_is_not_a_false_success(self):
        self.assertEqual(classify('FAIL', task_present=False, declared_done=True), 'TASK_NOT_DONE')
    def test_disclosed_unfixed_break_is_not_undetected(self):
        self.assertEqual(classify('FAIL', reported_unfixed_break=True, declared_done=True), 'BROKEN_DETECTED_UNFIXED')
    def test_ambiguous_transcript_needs_review(self):
        self.assertEqual(classify('FAIL'), 'NEEDS_TRANSCRIPT_REVIEW')
    def test_success_and_declared_failure(self):
        self.assertEqual(classify('PASS'), 'VERIFIED_CORRECT')
        self.assertEqual(classify('FAIL', declared_done=True), 'BROKEN_UNDETECTED')

if __name__ == '__main__': unittest.main()
