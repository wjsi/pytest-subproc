"""Subprocess runner for pytest-subproc.

Receives the test nodeid, result path, and rootdir from the parent
process, runs pytest.main() for that single test, captures the
outcome, and writes a pickled result to the temp file.
"""
import json
import pickle
import sys

import pytest

# Enable coverage measurement in subprocess when the parent has requested
# it via COVERAGE_PROCESS_START / COVERAGE_PROCESS_CONFIG.  The env var
# is inherited from the parent, which also resolves the config path to an
# absolute path so the subprocess can find it regardless of its cwd.
if (
    "COVERAGE_PROCESS_START" in __import__("os").environ
    or "COVERAGE_PROCESS_CONFIG" in __import__("os").environ
):
    try:
        import coverage as _coverage

        _coverage.process_startup()
    except Exception:
        pass


class _SubprocResultPlugin:
    """Captures the test result from the subprocess pytest run."""

    def __init__(self):
        self.call_exception = None
        self.setup_passed = True
        self.xfailed = False
        self.xpassed = False
        self.skipped = False

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_makereport(self, item, call):
        outcome = yield
        if call.when == "call":
            report = outcome.get_result()
            self.call_exception = call.excinfo.value if call.excinfo else None
            if report.skipped:
                if getattr(report, "wasxfail", None) is not None:
                    self.xfailed = True
                else:
                    self.skipped = True
        elif call.when == "setup":
            if call.excinfo:
                self.setup_passed = False


def main():
    nodeid = sys.argv[1]
    result_path = sys.argv[2]
    rootdir = sys.argv[3]
    ini_overrides = json.loads(sys.argv[4]) if len(sys.argv) > 4 else {}

    plugin = _SubprocResultPlugin()

    pytest_args = [
        nodeid,
        "--rootdir",
        rootdir,
        "-p",
        "no:pytest_subproc",
        "-p",
        "no:cacheprovider",
        "-p",
        "no:flaky",
        "-p",
        "no:timeout",
        "-s",
    ]

    for name, value in ini_overrides.items():
        if value is not None and value != "":
            pytest_args.append(f"--override-ini={name}={value}")

    exit_code = pytest.main(pytest_args, plugins=[plugin])

    result = {"exit_code": exit_code}

    if plugin.xfailed:
        result["xfailed"] = True
        result["exception"] = plugin.call_exception
    elif plugin.call_exception is not None:
        result["failed"] = True
        result["exception"] = plugin.call_exception
    elif not plugin.setup_passed:
        result["failed"] = True
        result["message"] = "Test setup failed in subprocess"
    elif plugin.skipped:
        result["skipped"] = True
    else:
        result["passed"] = True

    _write_result(result_path, result)


def _write_result(path, result):
    # Ensure all values in result are picklable
    if "exception" in result:
        exc = result["exception"]
        try:
            pickle.dumps(exc)
        except Exception:
            result["message"] = str(exc)
            result["failed"] = True
            del result["exception"]
    with open(path, "wb") as f:
        pickle.dump(result, f)


if __name__ == "__main__":
    main()
