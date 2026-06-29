import importlib.util
import os
import pathlib
import sys
import types
import uuid

import pytest


def _required_path(name):
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"missing required environment variable: {name}")

    path = pathlib.Path(value)
    if not path.exists():
        raise RuntimeError(f"path from {name} does not exist: {path}")
    return path


def _build_fake_xspcomm():
    xsp_mod = types.ModuleType("xspcomm")

    class FakeXClock:
        def __init__(self, step_func, dut=None):
            self.step_func = step_func
            self.dut = dut

        def Add(self, *_args, **_kwargs):
            return None

        def getEvent(self):
            return object()

        def Step(self, *_args, **_kwargs):
            return None

        def StepRis(self, *_args, **_kwargs):
            return None

        def StepFal(self, *_args, **_kwargs):
            return None

    class FakeXPort(dict):
        def Add(self, name, xdata):
            self[name] = xdata

    class FakeXSignalCFG:
        def __init__(self, *_args, **_kwargs):
            pass

    class FakeXData:
        In = 0
        Out = 1

        def __init__(self, width, direction):
            self.width = width
            self.direction = direction

    class FakeXPin:
        def __init__(self, xdata, event):
            self.xdata = xdata
            self.event = event
            self.value = 0

        def BindDPIPtr(self, *_args, **_kwargs):
            return None

    xsp_mod.XClock = FakeXClock
    xsp_mod.XPort = FakeXPort
    xsp_mod.XSignalCFG = FakeXSignalCFG
    xsp_mod.XData = FakeXData
    xsp_mod.XPin = FakeXPin
    return xsp_mod


class FakeUnifiedBase:
    live_count = 0
    finish_calls = 0

    def __init__(self, *args):
        type(self).live_count += 1
        self.args = args
        self.pxcStep = 0x1234
        self.pSelf = 0x5678

    def GetXSignalCFGPath(self):
        return ""

    def GetXSignalCFGBasePtr(self):
        return 0

    def GetDPIHandle(self, *_args, **_kwargs):
        return 0

    def ResumeWaveformDump(self):
        return True

    def PauseWaveformDump(self):
        return True

    def WaveformPaused(self):
        return 0

    def SetWaveform(self, *_args, **_kwargs):
        return None

    def GetWaveFormat(self):
        return "fsdb"

    def FlushWaveform(self):
        return None

    def SetCoverage(self, *_args, **_kwargs):
        return None

    def GetCovMetrics(self):
        return 0

    def CheckPoint(self, *_args, **_kwargs):
        return 0

    def Restore(self, *_args, **_kwargs):
        return 0

    def GetVPIHandleObj(self, *_args, **_kwargs):
        return 0

    def GetVPIFuncPtr(self, *_args, **_kwargs):
        return 0

    def VPIInternalSignalList(self, *_args, **_kwargs):
        return []

    def RefreshComb(self):
        return None

    def atClone(self):
        return None

    def Finish(self):
        type(self).finish_calls += 1
        return 0


@pytest.fixture(autouse=True)
def clear_runtime_env(monkeypatch):
    for name in (
        "PYTEST_CURRENT_TEST",
        "PICKER_SHARE_RUNTIME",
        "PICKER_DISABLE_SHARED_RUNTIME",
        "LD_PRELOAD",
        "_PICKER_LD_PRELOAD_HANDLED",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(scope="session")
def generated_dut_path():
    return _required_path("PICKER_TEST_GENERATED_DUT")


@pytest.fixture(scope="session")
def generated_top_sv_path():
    return _required_path("PICKER_TEST_GENERATED_TOP_SV")


@pytest.fixture
def generated_module(generated_dut_path):
    fake_xspcomm = _build_fake_xspcomm()
    module_name = f"generated_vcs_dut_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, generated_dut_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load module spec from {generated_dut_path}")

    module = importlib.util.module_from_spec(spec)
    previous_xspcomm = sys.modules.get("xspcomm")
    sys.modules["xspcomm"] = fake_xspcomm
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.modules.pop(module_name, None)
        if previous_xspcomm is None:
            sys.modules.pop("xspcomm", None)
        else:
            sys.modules["xspcomm"] = previous_xspcomm


@pytest.fixture
def runtime_module(generated_module, monkeypatch):
    FakeUnifiedBase.live_count = 0
    FakeUnifiedBase.finish_calls = 0
    generated_module.DutUnifiedBase = FakeUnifiedBase
    monkeypatch.setattr(generated_module, "_load_dut_bindings", lambda: None)
    monkeypatch.setattr(generated_module.atexit, "register", lambda _fn: None)
    generated_module.DUTAdder._shared_instance = None
    generated_module.DUTAdder._shared_cleanup_registered = False
    return generated_module
