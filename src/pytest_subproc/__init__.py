import json
import os
import pickle
import signal
import subprocess
import sys
import tempfile
import warnings

import pytest

_INI_FORWARD_NAMES = [
    "asyncio_mode",
    "asyncio_default_fixture_loop_scope",
    "xfail_strict",
    "log_cli",
]


def _forward_ini_overrides(config):
    overrides = {}
    for name in _INI_FORWARD_NAMES:
        try:
            val = config.getini(name)
            if val is not None and val != "":
                if isinstance(val, (list, tuple)):
                    parts = [str(v) for v in val if v]
                    val = " ".join(parts) if parts else None
                elif hasattr(val, "value"):
                    val = val.value
                else:
                    val = str(val)
                if val is not None and val != "":
                    overrides[name] = val
        except (ValueError, KeyError):
            pass
    return overrides


@pytest.hookimpl(tryfirst=True)
def pytest_pyfunc_call(pyfuncitem):
    """Run marked tests in a subprocess instead of in-process.

    Hooking the call phase (rather than owning ``pytest_runtest_protocol``)
    lets the default runtest protocol -- and wrappers such as ``flaky`` --
    drive setup, teardown and retries.  Returning a non-None value stops the
    default ``pytest_pyfunc_call`` (a ``firstresult`` hook) from executing
    the test body in the parent process.
    """
    if not _should_spawn(pyfuncitem):
        return None

    _cancel_pytest_timeout(pyfuncitem)
    timeout = _resolve_timeout(pyfuncitem)

    try:
        result = run_subprocess_test(pyfuncitem, pyfuncitem.nodeid, timeout)
    except TimeoutError as exc:
        pytest.fail(str(exc))

    stdout = result.get("_stdout", "")
    stderr = result.get("_stderr", "")

    if result.get("passed"):
        return True

    if "exception" in result:
        exc = result["exception"]
        msg = _build_exception_message(exc, stdout, stderr)
        if msg != str(exc):
            try:
                exc.args = (msg, *exc.args[1:])
            except Exception:
                pass
        raise exc

    base = result.get("message", "Test failed in subprocess")
    msg = _build_exception_message(Exception(base), stdout, stderr)
    pytest.fail(msg)


def _get_pytest_timeout_marker(item):
    """Get timeout value from @pytest.mark.timeout marker, if any."""
    for marker in item.iter_markers(name="timeout"):
        if marker.args:
            try:
                return float(marker.args[0])
            except (ValueError, TypeError):
                pass
        kwargs_timeout = marker.kwargs.get("timeout")
        if kwargs_timeout is not None:
            try:
                return float(kwargs_timeout)
            except (ValueError, TypeError):
                pass
    return None


_config_default_timeout = None
_config_global_enabled = None


def config_default_timeout(value=None):
    if value is not None:
        global _config_default_timeout
        _config_default_timeout = float(value)


def config_global_enabled(value=None):
    if value is not None:
        global _config_global_enabled
        _config_global_enabled = value


def _resolve_timeout(item):
    candidates = []

    marker = item.get_closest_marker("subproc")
    if marker is not None:
        t = marker.kwargs.get("timeout")
        if t is not None:
            candidates.append(("subproc marker", float(t)))

    pt = _get_pytest_timeout_marker(item)
    if pt is not None:
        candidates.append(("pytest-timeout marker", pt))

    if candidates:
        candidates.sort(key=lambda x: x[1])
        return candidates[0][1]

    def resolve_cfg_timeout(v):
        if isinstance(v, list) and len(v) > 0:
            v = v[0]
        if v is None or v == "":
            return
        try:
            return float(v)
        except (ValueError, TypeError):
            pass

    cli = resolve_cfg_timeout(
        item.config.getoption("subproc_default_timeout", default=None)
    )
    if cli is not None:
        return cli

    ini = resolve_cfg_timeout(item.config.getini("subproc_default_timeout"))
    if ini is not None:
        return ini

    if _config_default_timeout is not None:
        return _config_default_timeout

    return None


def _should_spawn(item):
    marker = item.get_closest_marker("subproc")
    if marker is None:
        return False
    if "condition" in marker.kwargs:
        condition = marker.kwargs["condition"]
        if callable(condition):
            return condition()
        return bool(condition)
    if _config_global_enabled is not None:
        if callable(_config_global_enabled):
            return _config_global_enabled()
        return _config_global_enabled
    return True


def _get_timeout(item):
    return _resolve_timeout(item)


def _cancel_pytest_timeout(item):
    """Cancel pytest-timeout's timeout for this test item.

    pytest-timeout stores a ``cancel_timeout`` callable on the item
    that stops the timer thread.  Calling it prevents the timer from
    killing the parent while we wait for the subprocess.
    """
    try:
        cancel = getattr(item, "cancel_timeout", None)
        if cancel is not None:
            cancel()
    except Exception:
        pass


def _kill_process_tree(proc):
    """Kill the subprocess and its entire process group / tree."""
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                timeout=5,
            )
        else:
            pgid = os.getpgid(proc.pid)
            os.killpg(pgid, signal.SIGKILL)
    except (OSError, subprocess.TimeoutExpired, Exception):
        try:
            proc.kill()
        except Exception:
            pass


def run_subprocess_test(item, nodeid, timeout):
    runner_path = os.path.join(os.path.dirname(__file__), "_subproc_runner.py")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pkl") as f:
        result_path = f.name

    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(sys.path)

    rootdir = str(item.config.rootpath)

    ini_overrides = _forward_ini_overrides(item.config)

    args = [
        sys.executable,
        runner_path,
        nodeid,
        result_path,
        rootdir,
        json.dumps(ini_overrides),
    ]

    popen_kwargs = dict(
        args=args,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    if sys.platform != "win32":
        popen_kwargs["start_new_session"] = True

    proc = subprocess.Popen(**popen_kwargs)

    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_process_tree(proc)
        stdout, stderr = proc.communicate()
        try:
            os.unlink(result_path)
        except OSError:
            pass
        raise TimeoutError(f"Test timed out after {timeout}s")
    except BaseException:
        _kill_process_tree(proc)
        stdout, stderr = proc.communicate()
        try:
            os.unlink(result_path)
        except OSError:
            pass
        raise

    try:
        with open(result_path, "rb") as f:
            data_bytes = f.read()
        if data_bytes:
            result = pickle.loads(data_bytes)
        else:
            result = {
                "failed": True,
                "message": f"Subprocess crashed (exit code {proc.returncode})",
            }
    except FileNotFoundError:
        result = {
            "failed": True,
            "message": f"Subprocess crashed (exit code {proc.returncode})",
        }
    except (pickle.UnpicklingError, EOFError, Exception):
        result = {
            "failed": True,
            "message": f"Subprocess crashed (exit code {proc.returncode})",
        }
    finally:
        try:
            os.unlink(result_path)
        except OSError:
            pass

    result["_stdout"] = stdout.decode(errors="replace")
    result["_stderr"] = stderr.decode(errors="replace")

    return result


def _build_exception_message(exc, stdout, stderr):
    msg = str(exc) if str(exc) else ""
    if stdout:
        msg += f"\n[subproc stdout]\n{stdout}"
    if stderr:
        msg += f"\n[subproc stderr]\n{stderr}"
    return msg


def pytest_addoption(parser):
    parser.addini(
        "subproc_default_timeout",
        type="string",
        default=None,
        help="Default timeout in seconds for subprocess tests (int or float)",
    )
    parser.addoption(
        "--subprocess-timeout",
        dest="subproc_default_timeout",
        type=str,
        default=None,
        metavar="SECONDS",
        help="Default timeout in seconds for @pytest.mark.subproc tests",
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "subproc(timeout=None, condition=None): "
        "run the marked test in a subprocess. "
        "timeout: timeout in seconds. "
        "condition: bool or callable to decide whether to use subprocess.",
    )

    raw = config.getini("subproc_default_timeout")
    if raw is not None and raw != "":
        try:
            float(raw)
        except (ValueError, TypeError):
            warnings.warn(
                f"subproc_default_timeout = {raw!r} is not a valid number; "
                "ignoring.  Set it to a float or int, e.g. "
                "subproc_default_timeout = 30",
                pytest.PytestConfigWarning,
            )
