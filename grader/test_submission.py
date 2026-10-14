import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch

import grade


class BlindSubmissionTests(unittest.TestCase):
    def check_rejected(self, metadata):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            run = root / 'runs' / 'opaque01'
            run.mkdir(parents=True)
            (run / 'submission.json').write_text(json.dumps(metadata))
            with patch.object(grade, 'ROOT', root), patch.object(grade.subprocess, 'run') as command:
                with self.assertRaises(ValueError):
                    grade.main('opaque01')
                command.assert_not_called()

    def test_arm_metadata_never_reaches_grading(self):
        self.check_rejected({'task':'t1', 'base_sha':grade.PINS['hotrod_sha'], 'arm':'b'})

    def test_unknown_task_is_rejected_before_starting_workers(self):
        self.check_rejected({'task':'t3', 'base_sha':grade.PINS['hotrod_sha']})

    def test_wrong_source_revision_is_rejected_before_starting_workers(self):
        self.check_rejected({'task':'t1', 'base_sha':'0' * 40})

    def test_run_id_cannot_escape_the_submission_directory(self):
        with patch.object(grade.subprocess, 'run') as command:
            with self.assertRaises(ValueError):
                grade.main('../other-project')
            command.assert_not_called()


if __name__ == '__main__':
    unittest.main()
