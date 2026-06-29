import pytest


@pytest.mark.parametrize("value", ["1", "true", "TRUE", " yes ", "On"])
def test_env_flag_accepts_truthy_spellings(generated_module, monkeypatch, value):
    monkeypatch.setenv("PICKER_TEST_FLAG", value)
    assert generated_module._env_flag("PICKER_TEST_FLAG") is True


@pytest.mark.parametrize("value", ["", "0", "false", "off", "random-value"])
def test_env_flag_rejects_non_truthy_spellings(generated_module, monkeypatch, value):
    monkeypatch.setenv("PICKER_TEST_FLAG", value)
    assert generated_module._env_flag("PICKER_TEST_FLAG") is False


@pytest.mark.parametrize(
    "requires_preload,running_under_pytest,share_env,disable_env,expected",
    [
        (False, False, None, None, False),
        (True, False, None, None, False),
        (True, True, None, None, True),
        (True, False, "1", None, True),
        (True, True, None, "1", False),
        (True, False, "1", "1", False),
    ],
)
def test_should_share_runtime_precedence(
    generated_module,
    monkeypatch,
    requires_preload,
    running_under_pytest,
    share_env,
    disable_env,
    expected,
):
    monkeypatch.setattr(generated_module, "_requires_preload", lambda: requires_preload)
    monkeypatch.setattr(generated_module, "_running_under_pytest", lambda: running_under_pytest)
    if share_env is not None:
        monkeypatch.setenv("PICKER_SHARE_RUNTIME", share_env)
    if disable_env is not None:
        monkeypatch.setenv("PICKER_DISABLE_SHARED_RUNTIME", disable_env)

    assert generated_module._should_share_runtime() is expected
