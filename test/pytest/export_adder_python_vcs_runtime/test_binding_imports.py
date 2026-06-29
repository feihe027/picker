import types

import pytest


def test_load_dut_bindings_static_tls_error_mentions_ld_preload(generated_module, monkeypatch):
    monkeypatch.setattr(
        generated_module,
        "import_module",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ImportError("static TLS block")),
    )
    generated_module._BINDINGS_MODULE = None

    with pytest.raises(ImportError, match="LD_PRELOAD="):
        generated_module._load_dut_bindings()

    assert generated_module._BINDINGS_MODULE is None


def test_load_dut_bindings_passthrough_import_error(generated_module, monkeypatch):
    monkeypatch.setattr(
        generated_module,
        "import_module",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ImportError("plain import failure")),
    )
    generated_module._BINDINGS_MODULE = None

    with pytest.raises(ImportError, match="plain import failure"):
        generated_module._load_dut_bindings()


def test_load_dut_bindings_caches_imported_module(generated_module, monkeypatch):
    fake_bindings = types.ModuleType("libUT_Adder")
    fake_bindings.DutUnifiedBase = object
    fake_bindings.exported_symbol = 123
    calls = []

    def fake_import(*args, **_kwargs):
        calls.append(args)
        return fake_bindings

    monkeypatch.setattr(generated_module, "import_module", fake_import)
    generated_module._BINDINGS_MODULE = None

    loaded = generated_module._load_dut_bindings()

    assert loaded is fake_bindings
    assert generated_module.exported_symbol == 123
    assert generated_module._load_dut_bindings() is fake_bindings
    assert len(calls) == 1
