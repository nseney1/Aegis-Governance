"""The developer's shell environment must not redirect the suite (tests/conftest.py).

AEGIS_WORKSPACE would point every CLI and MCP call at the developer's real
workspace; AEGIS_CLIENT, AEGIS_LLM_CMD and AEGIS_MAX_JIT_TOKENS change host
identity, the Layer-2 backend and scan budgets. The autouse fixture removes
them before each test; a test that needs one sets it with monkeypatch.
"""
import os

import pytest

AEGIS_ENV = ("AEGIS_WORKSPACE", "AEGIS_CLIENT", "AEGIS_LLM_CMD", "AEGIS_MAX_JIT_TOKENS")


@pytest.fixture(scope="module")
def developer_shell_env():
    """Simulate variables exported in the shell that launched pytest."""
    saved = {k: os.environ.get(k) for k in AEGIS_ENV}
    for key in AEGIS_ENV:
        os.environ[key] = f"/developer/{key.lower()}"
    yield
    for key, value in saved.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


@pytest.mark.parametrize("key", AEGIS_ENV)
def test_aegis_env_vars_are_absent_inside_each_test(developer_shell_env, key):
    assert key not in os.environ


def test_a_test_can_still_set_one_explicitly(developer_shell_env, monkeypatch, tmp_path):
    monkeypatch.setenv("AEGIS_WORKSPACE", str(tmp_path))
    assert os.environ["AEGIS_WORKSPACE"] == str(tmp_path)
