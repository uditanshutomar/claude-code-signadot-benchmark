"""Combine the blind grade with separately recorded session observations."""

def classify(grade_status, *, timed_out=False, task_present=None, declared_done=None, reported_unfixed_break=None):
    if grade_status == 'HARNESS_ERROR':
        return 'HARNESS_ERROR'
    if timed_out:
        return 'DID_NOT_FINISH'
    if grade_status == 'PASS':
        return 'VERIFIED_CORRECT'
    if task_present is False:
        return 'TASK_NOT_DONE'
    if reported_unfixed_break is True:
        return 'BROKEN_DETECTED_UNFIXED'
    if declared_done is True:
        return 'BROKEN_UNDETECTED'
    # Do not manufacture the agent's intent from a failing HTTP request.
    return 'NEEDS_TRANSCRIPT_REVIEW'
