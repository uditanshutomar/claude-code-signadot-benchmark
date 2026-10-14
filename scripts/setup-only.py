#!/usr/bin/env python3
"""Run a setup command with OpenTelemetry export disabled.

This controls the child environment, not a container's own saved settings.
Worker settings and network restrictions must also be set before agent use.
"""
import os
import subprocess
import sys


def setup_environment(original):
    env = {
        key: value for key, value in original.items()
        if not key.startswith(("OTEL_", "CODETELEMETRY_", "CLAUDE_CODE_ENABLE_TELEMETRY"))
    }
    env.update({
        "OTEL_SDK_DISABLED": "true",
        "OTEL_METRICS_EXPORTER": "none",
        "OTEL_LOGS_EXPORTER": "none",
        "OTEL_TRACES_EXPORTER": "none",
        "CLAUDE_CODE_ENABLE_TELEMETRY": "0",
        "SBX_NO_TELEMETRY": "1",
        "GOTELEMETRY": "off",
    })
    return env


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Usage: setup-only.py COMMAND [ARG ...]")
    # Preserve signals and exit codes, including timeout termination.
    os.execvpe(sys.argv[1], sys.argv[1:], setup_environment(os.environ))
