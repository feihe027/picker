def test_non_pytest_instances_are_not_shared(runtime_module, monkeypatch):
    monkeypatch.setattr(runtime_module, "_running_under_pytest", lambda: False)

    first = runtime_module.DUTAdder()
    second = runtime_module.DUTAdder()

    assert first is not second

    first.Finish()
    second.Finish()

    assert runtime_module.DutUnifiedBase.live_count == 2
    assert runtime_module.DutUnifiedBase.finish_calls == 2


def test_pytest_mode_reuses_single_runtime(runtime_module, monkeypatch):
    monkeypatch.setattr(runtime_module, "_running_under_pytest", lambda: True)

    first = runtime_module.DUTAdder()
    second = runtime_module.DUTAdder()

    assert first is second
    assert runtime_module.DutUnifiedBase.live_count == 1

    assert first.Finish() == 0
    assert runtime_module.DutUnifiedBase.finish_calls == 0

    assert first.Shutdown() == 0
    assert runtime_module.DutUnifiedBase.finish_calls == 1


def test_shutdown_rebuilds_shared_runtime(runtime_module, monkeypatch):
    monkeypatch.setattr(runtime_module, "_running_under_pytest", lambda: True)

    first = runtime_module.DUTAdder()
    first.Shutdown()
    second = runtime_module.DUTAdder()

    assert second is not first
    assert runtime_module.DutUnifiedBase.live_count == 2

    second.Shutdown()
    assert runtime_module.DutUnifiedBase.finish_calls == 2


def test_disable_shared_runtime_overrides_pytest(runtime_module, monkeypatch):
    monkeypatch.setattr(runtime_module, "_running_under_pytest", lambda: True)
    monkeypatch.setenv("PICKER_DISABLE_SHARED_RUNTIME", "1")

    first = runtime_module.DUTAdder()
    second = runtime_module.DUTAdder()

    assert first is not second

    first.Finish()
    second.Finish()
    assert runtime_module.DutUnifiedBase.finish_calls == 2


def test_explicit_share_runtime_works_outside_pytest(runtime_module, monkeypatch):
    monkeypatch.setattr(runtime_module, "_running_under_pytest", lambda: False)
    monkeypatch.setenv("PICKER_SHARE_RUNTIME", "1")

    first = runtime_module.DUTAdder()
    second = runtime_module.DUTAdder()

    assert first is second
    assert runtime_module.DutUnifiedBase.live_count == 1

    first.Shutdown()
    assert runtime_module.DutUnifiedBase.finish_calls == 1
