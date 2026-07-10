# pytest-subproc

Run marked pytest test functions in an isolated subprocess to protect the main process from crashes caused by C++ panics, segfaults, or hangs.

## Installation

```bash
pip install pytest-subproc
```

## Usage

Mark any test with `@pytest.mark.subproc` to run it in a subprocess:

```python
import pytest

@pytest.mark.subproc
def test_isolated():
    assert True
```

### Parameters

`@pytest.mark.subproc(timeout=None, condition=None)`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `timeout` | `float` | `None` | Timeout in seconds. Kills the subprocess if the test exceeds this limit. Falls back to `subproc_default_timeout` ini option. |
| `condition` | `bool` or `() -> bool` | `True` | When falsy, the test runs in the main process normally. Useful for conditional isolation (e.g., only in CI). |

```python
@pytest.mark.subproc(timeout=30)
def test_with_timeout():
    ...

@pytest.mark.subproc(condition=lambda: os.environ.get("CI") == "true")
def test_ci_only():
    ...

@pytest.mark.subproc(timeout=10, condition=False)
def test_never_subprocess():
    ...
```

### Configuration via `pyproject.toml` / `pytest.ini`

```ini
[tool.pytest.ini_options]
subproc_default_timeout = 30
```

Or on the command line:

```bash
pytest --subprocess-timeout=30
```

### Module-level configuration

Set defaults for all `@pytest.mark.subproc` tests in a directory tree by calling `pytest_subproc` methods in a `conftest.py`:

```python
import pytest_subproc

# Default timeout (lowest priority: marker > CLI > ini > this)
pytest_subproc.config_default_timeout(30)

# Default condition for spawning (lowest priority: marker > this)
pytest_subproc.config_global_enabled(True)
pytest_subproc.config_global_enabled(lambda: os.environ.get("CI") == "true")  # callable
```


### `@pytest.mark.timeout` interaction

When a test has both `@pytest.mark.subproc(timeout=5)` and `@pytest.mark.timeout(3)`,
the shorter value (3s) is used as the subprocess timeout.  This prevents
`pytest-timeout` from killing the main process while the subprocess is still
running — our plugin cancels `pytest-timeout`'s timer and enforces the
effective timeout on the subprocess itself.

```python
@pytest.mark.subproc(timeout=5)
@pytest.mark.timeout(3)       # ← effective timeout (shorter wins)
def test_obey_the_shorter():
    ...
```


## How It Works

1. **Interception** — `pytest_runtest_protocol` (tryfirst) takes over the
   protocol for `subproc`-marked tests.

2. **Isolated run** — The main process spawns a child that runs
   `pytest.main([nodeid, --rootdir, ...])` for that single test.
   The **full lifecycle** (conftest loading, fixture resolution, setup,
   call, teardown) happens inside the subprocess.

3. **Timeout & cleanup** — The child is created with `start_new_session`
   so the **entire process group** (including test‑spawned children) is
   killed when the timeout fires.

4. **Result** — A plugin inside the subprocess captures the outcome and
   exception; these are pickled to a temp file.  The parent re‑raises
   the exception so `xfail`, `skip`, etc. work as expected.

5. **Config parity** — `asyncio_mode`, `xfail_strict` and other ini
   settings are forwarded to the subprocess via `--override-ini`.

## Comparison with `pytest-forked`

| | `pytest-subproc` | `pytest-forked` |
|---|---|---|
| Mechanism | Spawns a new Python process (`subprocess`) | Forks the existing process (`os.fork`) |
| Fixtures | Re‑evaluated in the child (full conftest + fixture resolution) | Inherited from parent via copy‑on‑write |
| Windows | ✅ Supported | ❌ Not available |
| Crash isolation | Full — the child has its own PID and memory space; a segfault cannot reach the parent | Partial — forked process shares file descriptors and some kernel state with the parent |
| Timeout | Built‑in `timeout` parameter on the marker, with process‑tree termination | Only via external `pytest-timeout` plugin |
| Process‑tree cleanup | Kills the entire process group on timeout (`os.killpg` / `taskkill /T`) | No automatic child‑process cleanup |
| Startup cost | Moderate — a new Python interpreter starts and runs `pytest.main` for one test | Low — fork is (mostly) copy‑on‑write |
| `pytest-xdist` | ✅ Compatible | ✅ Compatible |

## Feature Compatibility

| Feature | Status |
|---|---|
| Python >= 3.7 | ✅ |
| Function, session, and module-level fixtures | ✅ |
| stdout/stderr captured and shown on failure | ✅ |
| `pytest.mark.asyncio` + `asyncio_mode = "auto"` | ✅ |
| `@pytest.mark.parametrize` | ✅ |
| `@pytest.mark.xfail(raises=...)` | ✅ |
| Custom exception pickling / re-raising | ✅ |
| `flaky` retries | ✅ |
| `pytest-timeout` signal handling | ✅ |
| `pytest-cov` coverage passthrough | ✅ |

## Requirements

- Python >= 3.7
- pytest >= 7.0

## License

MIT
