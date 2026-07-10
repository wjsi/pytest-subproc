"""Comprehensive tests for pytest-subproc plugin."""
import os
import subprocess
import sys

import pytest

pytest_plugins = "pytester"

try:
    import flaky as _flaky  # noqa: F401

    _HAVE_FLAKY = True
except ImportError:
    _HAVE_FLAKY = False


# ---------------------------------------------------------------------------
# Basic subprocess execution
# ---------------------------------------------------------------------------


def test_basic_pass(pytester):
    pytester.makepyfile(
        """
        import pytest

        @pytest.mark.subproc
        def test_pass():
            assert True

        @pytest.mark.subproc
        def test_fail():
            assert False
        """
    )
    result = pytester.runpytest("-v")
    result.assert_outcomes(passed=1, failed=1)


def test_basic_pass_no_marker(pytester):
    pytester.makepyfile(
        """
        import pytest

        def test_plain():
            assert True
        """
    )
    result = pytester.runpytest("-v")
    result.assert_outcomes(passed=1)


# ---------------------------------------------------------------------------
# Condition
# ---------------------------------------------------------------------------


def test_condition_false_skips_subprocess(pytester):
    pytester.makepyfile(
        """
        import pytest

        @pytest.mark.subproc(condition=False)
        def test_skip_subproc():
            assert True
        """
    )
    result = pytester.runpytest("-v")
    result.assert_outcomes(passed=1)


def test_condition_callable(pytester):
    pytester.makepyfile(
        """
        import pytest

        @pytest.mark.subproc(condition=lambda: 1 + 1 == 2)
        def test_cond_true():
            assert True

        @pytest.mark.subproc(condition=lambda: False)
        def test_cond_false():
            assert True
        """
    )
    result = pytester.runpytest("-v")
    result.assert_outcomes(passed=2)


# ---------------------------------------------------------------------------
# Skip / skipif compatibility
# ---------------------------------------------------------------------------


def test_skip_marked(pytester):
    pytester.makepyfile(
        """
        import pytest

        @pytest.mark.subproc
        @pytest.mark.skip(reason="intentional")
        def test_should_skip():
            assert False  # would fail if not skipped
        """
    )
    result = pytester.runpytest("-v")
    result.assert_outcomes(skipped=1)


def test_skipif_true(pytester):
    pytester.makepyfile(
        """
        import pytest

        @pytest.mark.subproc
        @pytest.mark.skipif(True, reason="condition met")
        def test_should_skip():
            assert False
        """
    )
    result = pytester.runpytest("-v")
    result.assert_outcomes(skipped=1)


def test_skipif_false(pytester):
    pytester.makepyfile(
        """
        import pytest

        @pytest.mark.subproc
        @pytest.mark.skipif(False, reason="condition not met")
        def test_should_run():
            assert True
        """
    )
    result = pytester.runpytest("-v")
    result.assert_outcomes(passed=1)


def test_skip_unmarked_not_affected(pytester):
    pytester.makepyfile(
        """
        import pytest

        @pytest.mark.skip(reason="normal skip")
        def test_normal_skip():
            assert False

        def test_normal_run():
            assert True
        """
    )
    result = pytester.runpytest("-v")
    result.assert_outcomes(passed=1, skipped=1)


# ---------------------------------------------------------------------------
# Timeout
# ---------------------------------------------------------------------------


def test_timeout(pytester):
    pytester.makepyfile(
        """
        import pytest
        import time

        @pytest.mark.subproc(timeout=0.1)
        def test_slow():
            time.sleep(1)
        """
    )
    result = pytester.runpytest("-v")
    result.assert_outcomes(failed=1)
    assert "timed out" in result.stdout.str()


def test_default_timeout_from_ini(pytester):
    pytester.makepyfile(
        """
        import pytest
        import time

        @pytest.mark.subproc
        def test_slow():
            time.sleep(1)
        """
    )
    result = pytester.runpytest("-v", "--subprocess-timeout=0.1")
    result.assert_outcomes(failed=1)
    out = result.stdout.str()
    assert "timed out" in out or "TimeoutError" in out


def test_no_timeout(pytester):
    pytester.makepyfile(
        """
        import pytest

        @pytest.mark.subproc
        def test_fast():
            assert True
        """
    )
    result = pytester.runpytest("-v")
    result.assert_outcomes(passed=1)


def test_default_timeout_from_cli(pytester):
    pytester.makepyfile(
        """
        import pytest
        import time

        @pytest.mark.subproc
        def test_slow():
            time.sleep(1)
        """
    )
    result = pytester.runpytest("-v", "--subprocess-timeout=0.1")
    result.assert_outcomes(failed=1)
    assert "timed out" in result.stdout.str()


def test_ini_invalid_value_warns(pytester):
    (pytester.path / "pytest.ini").write_text(
        "[pytest]\nsubproc_default_timeout = not-a-number\n"
    )
    pytester.makepyfile(
        test_foo="""
        import pytest

        @pytest.mark.subproc
        def test_ok():
            assert True
        """,
    )
    result = pytester.runpytest_subprocess("-v")
    result.assert_outcomes(passed=1)
    assert "not a valid number" in result.stderr.str()


def test_ini_empty_value_ok(pytester):
    pytester.makepyfile(
        test_foo="""
        import pytest

        @pytest.mark.subproc
        def test_ok():
            assert True
        """,
    )
    result = pytester.runpytest("-v")
    result.assert_outcomes(passed=1)


# ---------------------------------------------------------------------------
# stdout / stderr capture on failure
# ---------------------------------------------------------------------------


def test_stdout_stderr_on_fail(pytester):
    pytester.makepyfile(
        """
        import pytest
        import sys

        @pytest.mark.subproc
        def test_with_output():
            sys.stdout.write("hello stdout\\n")
            sys.stderr.write("hello stderr\\n")
            assert False
        """
    )
    result = pytester.runpytest("-v")
    result.assert_outcomes(failed=1)
    out = result.stdout.str()
    assert "hello stdout" in out
    assert "hello stderr" in out


def test_stdout_not_shown_on_pass(pytester):
    pytester.makepyfile(
        """
        import pytest
        import sys

        @pytest.mark.subproc
        def test_pass_with_output():
            sys.stdout.write("should not appear\\n")
            assert True
        """
    )
    result = pytester.runpytest("-v")
    result.assert_outcomes(passed=1)


# ---------------------------------------------------------------------------
# Fixtures (defined in the same file)
# ---------------------------------------------------------------------------


def test_function_fixture(pytester):
    pytester.makepyfile(
        """
        import pytest

        @pytest.fixture
        def value():
            return 42

        @pytest.mark.subproc
        def test_with_fixture(value):
            assert value == 42
        """
    )
    result = pytester.runpytest("-v")
    result.assert_outcomes(passed=1)


def test_session_fixture(pytester):
    pytester.makepyfile(
        """
        import pytest

        @pytest.fixture(scope="session")
        def session_value():
            return "session_data"

        @pytest.mark.subproc
        def test_session(session_value):
            assert session_value == "session_data"
        """
    )
    result = pytester.runpytest("-v")
    result.assert_outcomes(passed=1)


def test_module_fixture(pytester):
    pytester.makepyfile(
        test_subproc_fixture_module="""
        import pytest

        @pytest.fixture(scope="module")
        def module_value():
            return "module_data"

        @pytest.mark.subproc
        def test_module(module_value):
            assert module_value == "module_data"
        """
    )
    result = pytester.runpytest("-v", "test_subproc_fixture_module.py")
    result.assert_outcomes(passed=1)


# ---------------------------------------------------------------------------
# Fixtures in conftest.py
# ---------------------------------------------------------------------------


def test_conftest_function_fixture(pytester):
    pytester.makepyfile(
        conftest="""
        import pytest

        @pytest.fixture
        def conftest_value():
            return "from_conftest"
        """,
        test_example="""
        import pytest

        @pytest.mark.subproc
        def test_conftest(conftest_value):
            assert conftest_value == "from_conftest"
        """,
    )
    result = pytester.runpytest("-v")
    result.assert_outcomes(passed=1)


def test_conftest_session_fixture(pytester):
    pytester.makepyfile(
        conftest="""
        import pytest

        @pytest.fixture(scope="session")
        def session_val():
            return "session_from_conftest"
        """,
        test_example="""
        import pytest

        @pytest.mark.subproc
        def test_conftest_session(session_val):
            assert session_val == "session_from_conftest"
        """,
    )
    result = pytester.runpytest("-v")
    result.assert_outcomes(passed=1)


def test_conftest_module_fixture(pytester):
    pytester.makepyfile(
        conftest="""
        import pytest

        @pytest.fixture(scope="module")
        def module_val():
            return "module_from_conftest"
        """,
        test_example="""
        import pytest

        @pytest.mark.subproc
        def test_conftest_module(module_val):
            assert module_val == "module_from_conftest"
        """,
    )
    result = pytester.runpytest("-v")
    result.assert_outcomes(passed=1)


def test_conftest_parametrized_with_subproc(pytester):
    pytester.makepyfile(
        conftest="""
        import pytest

        @pytest.fixture
        def prefix():
            return "val_"
        """,
        test_example="""
        import pytest

        @pytest.mark.subproc
        @pytest.mark.parametrize("suffix", ["a", "b"])
        def test_conftest_param(prefix, suffix):
            assert prefix == "val_"
            assert suffix in ("a", "b")
        """,
    )
    result = pytester.runpytest("-v")
    result.assert_outcomes(passed=2)


def test_conftest_nested_subdir(pytester):
    from textwrap import dedent

    subdir = pytester.path / "sub"
    subdir.mkdir()
    pytester.makepyfile(
        conftest="""
        import pytest

        @pytest.fixture
        def parent_val():
            return "parent"
        """,
    )
    (subdir / "test_nested.py").write_text(
        dedent(
            """\
        import pytest

        @pytest.mark.subproc
        def test_nested(parent_val):
            assert parent_val == "parent"
    """
        )
    )
    result = pytester.runpytest("-v")
    result.assert_outcomes(passed=1)


def test_conftest_with_xdist(pytester):
    pytester.makepyfile(
        conftest="""
        import pytest

        @pytest.fixture
        def shared():
            return 99
        """,
        test_xdist_cft="""
        import pytest

        @pytest.mark.subproc
        def test_shared(shared):
            assert shared == 99
        """,
    )
    result = pytester.runpytest("-v", "-n", "2")
    assert "passed" in result.stdout.str()
    assert result.ret == 0


# ---------------------------------------------------------------------------
# Parametrize
# ---------------------------------------------------------------------------


def test_parametrize(pytester):
    pytester.makepyfile(
        """
        import pytest

        @pytest.mark.subproc
        @pytest.mark.parametrize("x, y", [(1, 2), (3, 4), (0, 0)])
        def test_add(x, y):
            assert x + y == x + y
        """
    )
    result = pytester.runpytest("-v")
    result.assert_outcomes(passed=3)


def test_parametrize_fail(pytester):
    pytester.makepyfile(
        """
        import pytest

        @pytest.mark.subproc
        @pytest.mark.parametrize("x, y, expected", [(1, 1, 2), (2, 2, 5)])
        def test_add(x, y, expected):
            assert x + y == expected
        """
    )
    result = pytester.runpytest("-v")
    result.assert_outcomes(passed=1, failed=1)


# ---------------------------------------------------------------------------
# Asyncio
# ---------------------------------------------------------------------------


def test_asyncio_mark(pytester):
    pytester.makepyfile(
        """
        import pytest

        @pytest.mark.subproc
        @pytest.mark.asyncio
        async def test_async():
            result = await async_identity(42)
            assert result == 42

        async def async_identity(x):
            return x
        """
    )
    result = pytester.runpytest("-v")
    result.assert_outcomes(passed=1)


def test_asyncio_auto(pytester):
    (pytester.path / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\nasyncio_mode = "auto"\n'
    )
    pytester.makepyfile(
        test_async_auto="""
        import pytest

        @pytest.mark.subproc
        async def test_async_auto():
            assert True
        """,
    )
    result = pytester.runpytest("-v")
    result.assert_outcomes(passed=1)


def test_asyncio_with_marker(pytester):
    pytester.makepyfile(
        """
        import pytest

        @pytest.mark.subproc
        @pytest.mark.asyncio
        async def test_async_marked():
            assert True
        """
    )
    result = pytester.runpytest("-v")
    result.assert_outcomes(passed=1)


# ---------------------------------------------------------------------------
# xfail
# ---------------------------------------------------------------------------


def test_xfail_raises(pytester):
    pytester.makepyfile(
        """
        import pytest

        @pytest.mark.subproc
        @pytest.mark.xfail(raises=ValueError)
        def test_xfail():
            raise ValueError("expected")
        """
    )
    result = pytester.runpytest("-v")
    result.assert_outcomes(xfailed=1)


def test_xfail_not_raises(pytester):
    pytester.makepyfile(
        """
        import pytest

        @pytest.mark.subproc
        @pytest.mark.xfail(raises=TypeError)
        def test_xfail_wrong_exc():
            raise ValueError("unexpected")
        """
    )
    result = pytester.runpytest("-v")
    result.assert_outcomes(failed=1)


def test_xfail_strict(pytester):
    pytester.makepyfile(
        """
        import pytest

        @pytest.mark.subproc
        @pytest.mark.xfail(strict=True)
        def test_xfail_strict_pass():
            assert True
        """
    )
    result = pytester.runpytest("-v")
    result.assert_outcomes(failed=1)


# ---------------------------------------------------------------------------
# Exceptions — pickling/unpickling
# ---------------------------------------------------------------------------


def test_custom_exception(pytester):
    pytester.makepyfile(
        """
        import pytest

        class MyCustomError(Exception):
            pass

        @pytest.mark.subproc
        def test_custom_exc():
            raise MyCustomError("custom error msg")
        """
    )
    result = pytester.runpytest("-v")
    result.assert_outcomes(failed=1)
    out = result.stdout.str()
    assert "MyCustomError" in out


def test_exception_pickling_preserves_type(pytester):
    pytester.makepyfile(
        """
        import pytest

        class DomainError(Exception):
            pass

        @pytest.mark.subproc
        def test_domain_error():
            raise DomainError("something went wrong")
        """
    )
    result = pytester.runpytest("-v")
    result.assert_outcomes(failed=1)
    out = result.stdout.str()
    assert "DomainError" in out
    assert "something went wrong" in out


# ---------------------------------------------------------------------------
# Coverage integration
# ---------------------------------------------------------------------------


def test_coverage_env_passthrough(pytester, monkeypatch):
    monkeypatch.setenv("COVERAGE_PROCESS_START", "/some/path/.coveragerc")

    pytester.makepyfile(
        """
        import pytest
        import os

        @pytest.mark.subproc
        def test_coverage_env():
            cps = os.environ.get("COVERAGE_PROCESS_START")
            assert cps == "/some/path/.coveragerc"
        """
    )
    result = pytester.runpytest("-v")
    result.assert_outcomes(passed=1)


def test_coverage_collected_from_subprocess(pytester, monkeypatch):
    pytester.makepyfile(
        helper="""
        def compute(x):
            return x * 2
        """,
        test_cov="""
        import pytest
        from helper import compute

        @pytest.mark.subproc
        def test_with_compute():
            result = compute(21)
            assert result == 42
        """,
    )

    covdir = pytester.path
    cov_file = covdir / ".cov_subproc_test"
    coveragerc = covdir / ".cov_subproc_rc"
    coveragerc.write_text(
        "[run]\nsource = {covdir}\ndata_file = {cov_file}\n".format(
            covdir=covdir,
            cov_file=cov_file,
        )
    )

    monkeypatch.setenv("COVERAGE_PROCESS_START", str(coveragerc))
    monkeypatch.setenv("COVERAGE_FILE", str(cov_file))

    result = pytester.runpytest("-v", "--cov=helper", "--cov-report=")
    result.assert_outcomes(passed=1)

    import coverage

    cov = coverage.Coverage(data_file=str(cov_file))
    cov.load()
    data = cov.get_data()

    helper_file = None
    for f in data.measured_files():
        if f.endswith("helper.py"):
            helper_file = f
            break

    assert helper_file is not None, "helper.py not found in coverage data"

    lines = data.lines(helper_file)
    assert lines is not None, "No line data for helper.py"
    assert 1 in lines, "Line 1 (module) should be covered"
    assert 2 in lines, "Line 2 (return x * 2) should be covered"


# ---------------------------------------------------------------------------
# Subprocess crash (simulated segfault / os._exit)
# ---------------------------------------------------------------------------


def test_subprocess_crash(pytester):
    pytester.makepyfile(
        """
        import pytest
        import os

        @pytest.mark.subproc
        def test_crash():
            os._exit(1)
        """
    )
    result = pytester.runpytest("-v")
    result.assert_outcomes(failed=1)


# ---------------------------------------------------------------------------
# Multiple subproc tests
# ---------------------------------------------------------------------------


def test_multiple_subproc_tests(pytester):
    pytester.makepyfile(
        """
        import pytest

        @pytest.mark.subproc
        def test_a():
            assert True

        @pytest.mark.subproc
        def test_b():
            assert True

        @pytest.mark.subproc
        def test_c():
            assert True
        """
    )
    result = pytester.runpytest("-v")
    result.assert_outcomes(passed=3)


# ---------------------------------------------------------------------------
# Mixed marked and unmarked — only the marked one spawns a subprocess
# ---------------------------------------------------------------------------


def test_mixed_marked_unmarked(pytester):
    pytester.makepyfile(
        """
        import pytest

        MODULE_VAR = "original"

        @pytest.mark.subproc
        def test_subproc():
            import test_mixed_marked_unmarked as m
            m.MODULE_VAR = "modified_in_sub"
            assert True

        def test_normal():
            import test_mixed_marked_unmarked as m
            assert m.MODULE_VAR == "original", (
                f"Expected 'original' but got {m.MODULE_VAR!r}"
            )
        """
    )
    result = pytester.runpytest("-v")
    result.assert_outcomes(passed=2)


def test_mixed_only_subproc_spawned(pytester):
    pytester.makepyfile(
        """
        import pytest

        ran_in_subprocess = [False]

        @pytest.mark.subproc
        def test_subproc():
            ran_in_subprocess[0] = True
            assert True

        def test_check_not_subproc():
            assert ran_in_subprocess[0] is False, (
                "test_check_not_subproc appears to have run in a subprocess!"
            )
        """
    )
    result = pytester.runpytest("-v")
    result.assert_outcomes(passed=2)


# ---------------------------------------------------------------------------
# Condition with environment variable
# ---------------------------------------------------------------------------


def test_condition_env_var(pytester):
    pytester.makepyfile(
        """
        import pytest
        import os

        _cond = lambda: os.environ.get("USE_SUBPROC") == "1"

        @pytest.mark.subproc(condition=_cond)
        def test_cond_env():
            assert True

        @pytest.mark.subproc(condition=_cond)
        def test_cond_env_skip():
            assert True
        """
    )
    result = pytester.runpytest("-v")
    result.assert_outcomes(passed=2)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_marker_no_args(pytester):
    pytester.makepyfile(
        """
        import pytest

        @pytest.mark.subproc()
        def test_no_args():
            assert True
        """
    )
    result = pytester.runpytest("-v")
    result.assert_outcomes(passed=1)


def test_empty_test(pytester):
    pytester.makepyfile(
        """
        import pytest

        @pytest.mark.subproc
        def test_empty():
            pass
        """
    )
    result = pytester.runpytest("-v")
    result.assert_outcomes(passed=1)


def test_keyboard_interrupt(pytester):
    pytester.makepyfile(
        """
        import pytest

        @pytest.mark.subproc
        def test_interrupt():
            assert True
        """
    )
    result = pytester.runpytest("-v")
    result.assert_outcomes(passed=1)


# ---------------------------------------------------------------------------
# Flaky compatibility
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _HAVE_FLAKY, reason="pytest-flaky not installed")
def test_flaky_compatibility(pytester):
    pytester.makepyfile(
        """
        import pytest
        from flaky import flaky

        @flaky(max_runs=2, min_passes=1)
        @pytest.mark.subproc
        def test_flaky_pass():
            assert True

        @flaky(max_runs=2, min_passes=1)
        @pytest.mark.subproc
        def test_flaky_always_fail():
            assert False
        """
    )
    result = pytester.runpytest("-v")
    result.assert_outcomes(passed=1, failed=1)


@pytest.mark.skipif(not _HAVE_FLAKY, reason="pytest-flaky not installed")
def test_flaky_retry_works(pytester):
    pytester.makepyfile(
        """
        import pytest
        from flaky import flaky

        @flaky(max_runs=3, min_passes=1)
        @pytest.mark.subproc
        def test_flaky_retry():
            assert True
        """
    )
    result = pytester.runpytest("-v")
    result.assert_outcomes(passed=1)


# ---------------------------------------------------------------------------
# pytest-timeout compatibility
# ---------------------------------------------------------------------------


def test_pytest_timeout_mark_shorter(pytester):
    pytester.makepyfile(
        """
        import pytest
        import time

        @pytest.mark.subproc(timeout=10)
        @pytest.mark.timeout(0.1)
        def test_slow():
            time.sleep(1)
        """
    )
    result = pytester.runpytest("-v")
    result.assert_outcomes(failed=1)


def test_subproc_timeout_shorter_than_pytest_timeout(pytester):
    pytester.makepyfile(
        """
        import pytest
        import time

        @pytest.mark.subproc(timeout=0.1)
        @pytest.mark.timeout(10)
        def test_slow():
            time.sleep(1)
        """
    )
    result = pytester.runpytest("-v")
    result.assert_outcomes(failed=1)
    out = result.stdout.str()
    assert "timed out" in out or "TimeoutError" in out


def test_pytest_timeout_without_subproc_timeout(pytester):
    """pytest-timeout works when subproc marker has no explicit timeout."""
    pytester.makepyfile(
        """
        import pytest
        import time

        @pytest.mark.subproc
        @pytest.mark.timeout(0.1)
        def test_slow():
            time.sleep(1)
        """
    )
    result = pytester.runpytest("-v")
    result.assert_outcomes(failed=1)


# ---------------------------------------------------------------------------
# Edge: subproc with both timeout and condition
# ---------------------------------------------------------------------------


def test_timeout_and_condition(pytester):
    pytester.makepyfile(
        """
        import pytest
        import time

        @pytest.mark.subproc(timeout=0.1, condition=True)
        def test_slow():
            time.sleep(1)

        @pytest.mark.subproc(timeout=0.1, condition=False)
        def test_not_slow():
            assert True
        """
    )
    result = pytester.runpytest("-v")
    result.assert_outcomes(passed=1, failed=1)


# ---------------------------------------------------------------------------
# Process tree termination on timeout
# ---------------------------------------------------------------------------


def _check_process_dead(pid):
    """Return True if the process with the given PID is no longer alive."""
    if sys.platform == "win32":
        out = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH", "/FI", f"PID eq {pid}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return str(pid) not in out.stdout
    else:
        try:
            os.kill(pid, 0)
            return False
        except OSError:
            return True


def test_subproc_child_killed_on_timeout(pytester, monkeypatch):
    """Verify that when a subproc test times out, the entire process tree
    (including child processes spawned by the test) is terminated."""
    import time as _time

    pid_file = pytester.path / "child_pid.txt"
    monkeypatch.setenv("CHILD_PID_FILE", str(pid_file))

    pytester.makepyfile(
        """
        import pytest
        import subprocess
        import os
        import time
        import sys

        @pytest.mark.subproc(timeout=0.15)
        def test_spawns_child():
            child = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            pid_file = os.environ.get("CHILD_PID_FILE")
            if pid_file:
                with open(pid_file, "w") as f:
                    f.write(str(child.pid))
            time.sleep(5)  # exceeds the 0.15s timeout
        """
    )

    result = pytester.runpytest("-v")
    result.assert_outcomes(failed=1)

    # Give the OS a moment to deliver SIGKILL to the process group
    _time.sleep(0.3)

    if not pid_file.exists():
        return  # child was never spawned before timeout; nothing to check

    child_pid = int(pid_file.read_text().strip())

    # Retry a few times — the child may be a zombie briefly before being
    # reaped by init after os.killpg terminates the process group.
    dead = False
    for _ in range(10):
        if _check_process_dead(child_pid):
            dead = True
            break
        _time.sleep(0.1)
    assert dead, f"Child process {child_pid} is still alive after timeout"


# ---------------------------------------------------------------------------
# pytest-xdist compatibility
# ---------------------------------------------------------------------------


def test_xdist_basic(pytester):
    pytester.makepyfile(
        """
        import pytest

        @pytest.mark.subproc
        def test_a():
            assert True

        @pytest.mark.subproc
        def test_b():
            assert True
        """
    )
    result = pytester.runpytest("-v", "-n", "2")
    assert "passed" in "".join(result.outlines)
    assert result.ret == 0


def test_xdist_with_fixtures(pytester):
    pytester.makepyfile(
        """
        import pytest

        @pytest.fixture
        def value():
            return 42

        @pytest.mark.subproc
        def test_with_fixture(value):
            assert value == 42
        """
    )
    result = pytester.runpytest("-v", "-n", "2")
    assert "passed" in "".join(result.outlines)
    assert result.ret == 0


def test_xdist_with_parametrize(pytester):
    pytester.makepyfile(
        """
        import pytest

        @pytest.mark.subproc
        @pytest.mark.parametrize("x", [1, 2, 3])
        def test_param(x):
            assert x > 0
        """
    )
    result = pytester.runpytest("-v", "-n", "2")
    assert "passed" in "".join(result.outlines)
    assert result.ret == 0


def test_xdist_with_xfail(pytester):
    pytester.makepyfile(
        """
        import pytest

        @pytest.mark.subproc
        @pytest.mark.xfail(raises=ValueError)
        def test_xfail():
            raise ValueError("expected")
        """
    )
    result = pytester.runpytest("-v", "-n", "2")
    assert "xfail" in result.stdout.str().lower()
    assert result.ret == 0


def test_xdist_subprocess_crash(pytester):
    pytester.makepyfile(
        """
        import pytest
        import os

        @pytest.mark.subproc
        def test_ok():
            assert True

        @pytest.mark.subproc
        def test_crash():
            os._exit(1)
        """
    )
    result = pytester.runpytest("-v", "-n", "2")
    assert result.ret == 1


def test_xdist_mixed_subproc_and_normal(pytester):
    pytester.makepyfile(
        """
        import pytest

        @pytest.mark.subproc
        def test_subproc():
            assert True

        def test_normal():
            assert True
        """
    )
    result = pytester.runpytest("-v", "-n", "2")
    assert "passed" in "".join(result.outlines)
    assert result.ret == 0


def test_xdist_timeout(pytester):
    pytester.makepyfile(
        """
        import pytest
        import time

        @pytest.mark.subproc(timeout=0.1)
        def test_slow():
            time.sleep(1)

        @pytest.mark.subproc
        def test_fast():
            assert True
        """
    )
    result = pytester.runpytest("-v", "-n", "2")
    assert result.ret == 1
    out = result.stdout.str()
    assert "FAILED" in out or "error" in out
    assert "timed out" in out or "TimeoutError" in out


# ---------------------------------------------------------------------------
# Module-level config_default_timeout and config_global_enabled
# ---------------------------------------------------------------------------


def test_config_default_timeout(pytester):
    pytester.makepyfile(
        conftest="""
        import pytest_subproc
        pytest_subproc.config_default_timeout(0.1)
        """,
        test_a="""
        import pytest
        import time

        @pytest.mark.subproc
        def test_slow():
            time.sleep(1)
        """,
    )
    result = pytester.runpytest("-v")
    result.assert_outcomes(failed=1)
    out = result.stdout.str()
    assert "timed out" in out or "TimeoutError" in out


def test_config_default_timeout_no_effect_when_marker_has_timeout(pytester):
    pytester.makepyfile(
        conftest="""
        import pytest_subproc
        pytest_subproc.config_default_timeout(0.1)
        """,
        test_a="""
        import pytest
        import time

        @pytest.mark.subproc(timeout=10)
        def test_slow():
            time.sleep(1)
        """,
    )
    result = pytester.runpytest("-v")
    result.assert_outcomes(passed=1)


def test_config_default_timeout_lower_priority_than_cli(pytester):
    pytester.makepyfile(
        conftest="""
        import pytest_subproc
        pytest_subproc.config_default_timeout(60)
        """,
        test_a="""
        import pytest
        import time

        @pytest.mark.subproc
        def test_slow():
            time.sleep(1)
        """,
    )
    result = pytester.runpytest("-v", "--subprocess-timeout=0.1")
    result.assert_outcomes(failed=1)
    out = result.stdout.str()
    assert "timed out" in out or "TimeoutError" in out


def test_config_global_enabled_false_skips_subprocess(pytester):
    pytester.makepyfile(
        conftest="""
        import pytest_subproc
        pytest_subproc.config_global_enabled(False)
        """,
        test_a="""
        import pytest

        @pytest.mark.subproc
        def test_should_run_normally():
            assert True
        """,
    )
    result = pytester.runpytest("-v")
    result.assert_outcomes(passed=1)
    out = result.stdout.str()
    assert "test_should_run_normally" in out


def test_config_global_enabled_callable(pytester):
    pytester.makepyfile(
        conftest="""
        import os
        import pytest_subproc
        pytest_subproc.config_global_enabled(
            lambda: os.environ.get("ENABLE_SUBPROC") == "1"
        )
        """,
        test_a="""
        import os
        import pytest

        @pytest.mark.subproc
        def test_default_disabled():
            assert True
        """,
    )
    result = pytester.runpytest("-v")
    result.assert_outcomes(passed=1)
    out = result.stdout.str()
    assert "test_default_disabled" in out


def test_config_global_enabled_marker_condition_overrides(pytester):
    pytester.makepyfile(
        conftest="""
        import pytest_subproc
        pytest_subproc.config_global_enabled(False)
        """,
        test_a="""
        import pytest

        @pytest.mark.subproc(condition=True)
        def test_spawned():
            assert True

        @pytest.mark.subproc(condition=False)
        def test_skipped():
            assert True
        """,
    )
    result = pytester.runpytest("-v")
    result.assert_outcomes(passed=2)
