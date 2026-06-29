import pathlib
import sys

import pytest


class ExecveCalled(RuntimeError):
    pass


def test_requires_preload_for_vcs_wrapper(generated_module):
    assert generated_module._requires_preload() is True


def test_preload_library_path_returns_existing_candidate(generated_module, generated_dut_path):
    candidate = pathlib.Path(generated_dut_path).with_name("libUTAdder.so")
    candidate.touch()
    try:
        assert generated_module._preload_library_path() == str(candidate)
    finally:
        candidate.unlink()


def test_restart_with_preload_execs_current_python(generated_module, monkeypatch):
    captured = {}

    monkeypatch.setattr(generated_module, "_preload_library_path", lambda: "/tmp/libUTAdder.so")

    def fake_execve(executable, argv, env):
        captured["executable"] = executable
        captured["argv"] = argv
        captured["env"] = env
        raise ExecveCalled()

    monkeypatch.setattr(generated_module.os, "execve", fake_execve)
    monkeypatch.setenv("LD_PRELOAD", "/tmp/existing_preload.so")

    with pytest.raises(ExecveCalled):
        generated_module.restart_with_preload()

    assert captured["executable"] == sys.executable
    assert captured["argv"][0] == sys.executable
    assert captured["env"][generated_module._HANDLED_ENV] == "1"
    assert captured["env"]["LD_PRELOAD"] == "/tmp/libUTAdder.so:/tmp/existing_preload.so"


def test_restart_with_preload_is_noop_after_guard(generated_module, monkeypatch):
    monkeypatch.setenv(generated_module._HANDLED_ENV, "1")
    assert generated_module.restart_with_preload() is False


def test_restart_with_preload_errors_when_library_is_missing(generated_module, monkeypatch):
    monkeypatch.setattr(generated_module, "_preload_library_path", lambda: None)

    with pytest.raises(RuntimeError, match="Failed to locate libUTAdder.so"):
        generated_module.restart_with_preload()
