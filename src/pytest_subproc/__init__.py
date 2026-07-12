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


def _check_skip(item):
    for marker in item.iter_markers(name="skip"):
        condition = marker.kwargs.get("condition", True)
        if callable(condition):
            if not condition():
                continue
        elif not condition:
            continue
        reason = marker.kwargs.get(
            "reason",
            marker.args[0] if marker.args else "",
        )
        return reason
    for marker in item.iter_markers(name="skipif"):
        args = marker.args
        if not args:
            continue
        condition = args[0]
        if callable(condition):
            if not condition():
                continue
        elif not condition:
            continue
        return marker.kwargs.get("reason", "")
    return None


def _get_xfail_info(item):
    for marker in item.iter_markers(name="xfail"):
        run = marker.kwargs.get("run", True)
        strict = marker.kwargs.get("strict")
        if strict is None:
            strict = item.config.getini("xfail_strict")
        if strict is None:
            strict = item.config.getini("strict")
        raises = marker.kwargs.get("raises", None)
        if "condition" not in marker.kwargs:
            conditions = marker.args
        else:
            conditions = (marker.kwargs["condition"],)
        if not conditions:
            reason = marker.kwargs.get("reason", "")
            return {
                "reason": reason,
                "strict": strict,
                "raises": raises,
                "run": run,
            }
        for condition in conditions:
            result = condition() if callable(condition) else condition
            if result:
                reason = marker.kwargs.get("reason", "")
                return {
                    "reason": reason,
                    "strict": strict,
                    "raises": raises,
                    "run": run,
                }
    return None


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_protocol(item, nextitem):
    if not _should_spawn(item):
        return None

    item.ihook.pytest_runtest_logstart(
        nodeid=item.nodeid,
        location=item.location,
    )

    reason = _check_skip(item)
    if reason is not None:
        call = pytest.CallInfo.from_call(
            lambda: pytest.skip(reason),
            when="setup",
            reraise=None,
        )
        rep = item.ihook.pytest_runtest_makereport(item=item, call=call)
        item.ihook.pytest_runtest_logreport(report=rep)
        item.ihook.pytest_runtest_teardown(item=item, nextitem=nextitem)
        item.ihook.pytest_runtest_logfinish(
            nodeid=item.nodeid,
            location=item.location,
        )
        return True

    timeout = _resolve_timeout(item)

    try:
        item.ihook.pytest_runtest_setup(item=item)
        _cancel_pytest_timeout(item)
        result = run_subprocess_test(item, item.nodeid, timeout)
    except TimeoutError as exc:
        msg = str(exc)
        call = pytest.CallInfo.from_call(
            lambda: pytest.fail(msg),
            when="call",
            reraise=None,
        )
        rep = item.ihook.pytest_runtest_makereport(item=item, call=call)
        item.ihook.pytest_runtest_logreport(report=rep)
        item.ihook.pytest_runtest_teardown(item=item, nextitem=nextitem)
        item.ihook.pytest_runtest_logfinish(
            nodeid=item.nodeid,
            location=item.location,
        )
        return True
    except (pytest.fail.Exception, KeyboardInterrupt) as exc:
        msg = str(exc)
        call = pytest.CallInfo.from_call(
            lambda: pytest.fail(msg),
            when="call",
            reraise=None,
        )
        rep = item.ihook.pytest_runtest_makereport(item=item, call=call)
        item.ihook.pytest_runtest_logreport(report=rep)
        item.ihook.pytest_runtest_teardown(item=item, nextitem=nextitem)
        item.ihook.pytest_runtest_logfinish(
            nodeid=item.nodeid,
            location=item.location,
        )
        return True
    except BaseException:
        item.ihook.pytest_runtest_teardown(item=item, nextitem=nextitem)
        item.ihook.pytest_runtest_logfinish(
            nodeid=item.nodeid,
            location=item.location,
        )
        raise

    stdout = result.get("_stdout", "")
    stderr = result.get("_stderr", "")

    if result.get("passed"):
        call = pytest.CallInfo.from_call(
            lambda: None,
            when="call",
            reraise=None,
        )
    elif result.get("xfailed"):
        exc = result["exception"]

        def _raise_xfail():
            raise exc

        call = pytest.CallInfo.from_call(
            _raise_xfail,
            when="call",
            reraise=None,
        )
    elif "exception" in result:
        exc = result["exception"]
        msg = _build_exception_message(exc, stdout, stderr)
        if msg != str(exc):
            try:
                exc.args = (msg, *exc.args[1:])
            except Exception:
                pass

        def _raise():
            raise exc

        call = pytest.CallInfo.from_call(_raise, when="call", reraise=None)
    else:
        msg = result.get("message", "Test failed in subprocess")
        msg = _build_exception_message(Exception(msg), stdout, stderr)

        def _fail():
            pytest.fail(msg)

        call = pytest.CallInfo.from_call(
            _fail,
            when="call",
            reraise=None,
        )

    rep = item.ihook.pytest_runtest_makereport(item=item, call=call)
    item.ihook.pytest_runtest_logreport(report=rep)
    item.ihook.pytest_runtest_teardown(item=item, nextitem=nextitem)
    item.ihook.pytest_runtest_logfinish(
        nodeid=item.nodeid,
        location=item.location,
    )
    return True


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    if call.when != "call":
        return
    rep = outcome.get_result()
    if getattr(rep, "wasxfail", None) is not None:
        return
    xfail_info = _get_xfail_info(item)
    if xfail_info is None or not xfail_info.get("run", True):
        return
    if call.excinfo:
        raises = xfail_info["raises"]
        if raises is None or isinstance(call.excinfo.value, raises):
            rep.outcome = "skipped"
            rep.wasxfail = xfail_info["reason"]
    elif not rep.skipped:
        if xfail_info["strict"]:
            rep.outcome = "failed"
            rep.longrepr = "[XPASS(strict)] " + xfail_info["reason"]
        else:
            rep.outcome = "passed"
            rep.wasxfail = xfail_info["reason"]


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
