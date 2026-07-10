# pytest-subproc — AGENTS.md

## Commands

```bash
pip install -e ".[test]"          # editable + test deps
pytest tests/ -v --timeout=60     # run all tests
pytest tests/ -k "xfail" -v       # single topic
pre-commit run --all-files        # lint: flake8 + black + isort
```

Coverage (requires `pip install coverage`):

```bash
COVERAGE_PROCESS_START=pyproject.toml \
  coverage run -m pytest tests/ --timeout=60 -x
coverage combine
coverage report --include="src/pytest_subproc/*" --show-missing
```

Mark subprocess tests: `@pytest.mark.subproc(timeout=N, condition=bool_or_callable)`.

## Architecture

- Entry point: `src/pytest_subproc/__init__.py` — `pytest_runtest_protocol` (tryfirst) intercepts `subproc`-marked items.
- Subprocess runner: `src/pytest_subproc/_subproc_runner.py`. Runs `pytest.main([nodeid])` — conftest loading, fixture resolution, setup/call/teardown all happen inside the child.
- No `_pytest` private imports outside a single `_pytest.skipping` call (xfailed_key/evaluate).
- Result: exception is pickled from child, re-raised in parent so `xfail(raises=...)` works.

## Coverage quirk

`_subproc_runner.py` runs as `python _subproc_runner.py` (script, not module import). Coverage with `source = [...]` won't capture it because it's `__main__`. Must use `include = ["src/pytest_subproc/*"]` (path-based) in the coverage config, and set `COVERAGE_PROCESS_START` so the `.pth`-file auto-start mechanism fires in the child. The CI coverage step shows how.

## Testing quirks

- All tests use `pytester` fixture (built-in, just `pytest_plugins = "pytester"` in the test file).
- `assert_outcomes(passed=N, failed=N, xfailed=N)` is preferred over `fnmatch_lines`.
- Coverage integration test (`test_coverage_collected_from_subprocess`) uses isolated file names (`.cov_subproc_*`) to avoid polluting the parent coverage run.
- `pytest-flaky` on PyPI is called `flaky` — the dependency name is `flaky`, import is `from flaky import flaky`.
- Windows CI uses a reduced Python version matrix (3.8, 3.13) to stay within runner time limits.
