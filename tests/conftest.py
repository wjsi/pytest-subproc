import os
import sys

import pytest


@pytest.fixture(autouse=True)
def add_module_path():
    old_path = list(sys.path)
    try:
        mod_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        sys.path.insert(0, mod_path)
        yield
    finally:
        sys.path[:] = old_path
