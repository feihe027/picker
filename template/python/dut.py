#coding=utf8

import atexit
import os
import sys
from importlib import import_module

try:
    from . import xspcomm as xsp
except ImportError:
    import xspcomm as xsp

_HANDLED_ENV = "_PICKER_LD_PRELOAD_HANDLED"
_BINDINGS_MODULE = None


def _requires_preload():
    {% if __SIMULATOR__ == "vcs" or __SIMULATOR__ == "uvs" %}
    return True
    {% else %}
    return False
    {% endif %}


def _preload_library_path():
    if not _requires_preload():
        return None

    dut_dir = os.path.dirname(os.path.abspath(__file__))
    for preload_path in (
        os.path.join(dut_dir, "libUT{{__TOP_MODULE_NAME__}}.so"),
        os.path.join(dut_dir, "UT_{{__TOP_MODULE_NAME__}}", "libUT{{__TOP_MODULE_NAME__}}.so"),
        os.path.join(dut_dir, "{{__TOP_MODULE_NAME__}}", "libUT{{__TOP_MODULE_NAME__}}.so"),
        os.path.join(dut_dir, "{{__TOP_MODULE_NAME__}}", "UT_{{__TOP_MODULE_NAME__}}", "libUT{{__TOP_MODULE_NAME__}}.so"),
    ):
        if os.path.exists(preload_path):
            return preload_path
    return None


def _env_flag(name):
    value = os.environ.get(name, "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _running_under_pytest():
    return "pytest" in sys.modules or "PYTEST_CURRENT_TEST" in os.environ


def _should_share_runtime():
    # VCS/UVS load the simulator into the host Python process and cannot be
    # safely re-initialized per test case. Under pytest, default to a
    # process-wide shared runtime so repeated DUT() / Finish() cycles do not
    # crash the session. Scripts keep the historical per-instance behavior
    # unless the user opts in via PICKER_SHARE_RUNTIME=1.
    if not _requires_preload():
        return False
    if _env_flag("PICKER_DISABLE_SHARED_RUNTIME"):
        return False
    if _env_flag("PICKER_SHARE_RUNTIME"):
        return True
    return _running_under_pytest()


def restart_with_preload():
    """Re-exec the current Python process with the simulator wrapper preloaded.

    Call this at the start of a script before creating the DUT when running with
    VCS/UVS. The current process image is replaced exactly once.
    """
    if not _requires_preload() or _HANDLED_ENV in os.environ:
        return False

    preload_path = _preload_library_path()
    if preload_path is None:
        raise RuntimeError("Failed to locate libUT{{__TOP_MODULE_NAME__}}.so for simulator preload")

    env = os.environ.copy()
    current_preload = env.get("LD_PRELOAD")
    env["LD_PRELOAD"] = preload_path if not current_preload else f"{preload_path}:{current_preload}"
    env[_HANDLED_ENV] = "1"
    os.execve(sys.executable, [sys.executable] + sys.argv, env)


def _load_dut_bindings():
    global _BINDINGS_MODULE
    if _BINDINGS_MODULE is not None:
        return _BINDINGS_MODULE

    try:
        if __package__ or "." in __name__:
            module = import_module(".libUT_{{__TOP_MODULE_NAME__}}", __package__)
        else:
            module = import_module("libUT_{{__TOP_MODULE_NAME__}}")
    except ImportError as exc:
        {% if __SIMULATOR__ == "vcs" or __SIMULATOR__ == "uvs" %}
        if "static TLS block" not in str(exc):
            raise

        preload_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "libUT{{__TOP_MODULE_NAME__}}.so")
        raise ImportError(
            "Failed to load the {{__SIMULATOR__}} Python wrapper because the simulator library "
            f"was not preloaded. Start Python with LD_PRELOAD={preload_path}, or call "
            "restart_with_preload() from this module at the start of your script before "
            "creating the DUT."
        ) from exc
        {% else %}
        raise
        {% endif %}

    globals().update({name: value for name, value in vars(module).items() if not name.startswith("_")})
    _BINDINGS_MODULE = module
    return module


def __getattr__(name):
    module = _load_dut_bindings()
    try:
        return getattr(module, name)
    except AttributeError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc


class DUT{{__TOP_MODULE_NAME__}}(object):

    _shared_instance = None
    _shared_cleanup_registered = False

    def __new__(cls, *args, **kwargs):
        if _should_share_runtime():
            if cls._shared_instance is None:
                instance = super().__new__(cls)
                instance._picker_initialized = False
                instance._picker_runtime_closed = False
                instance._picker_shared_runtime = True
                cls._shared_instance = instance
                if not cls._shared_cleanup_registered:
                    atexit.register(cls._shutdown_shared_runtime)
                    cls._shared_cleanup_registered = True
            return cls._shared_instance

        instance = super().__new__(cls)
        instance._picker_initialized = False
        instance._picker_runtime_closed = False
        instance._picker_shared_runtime = False
        return instance

    @classmethod
    def _shutdown_shared_runtime(cls):
        instance = cls._shared_instance
        if instance is None:
            return
        instance._finish_runtime()
        cls._shared_instance = None

    # initialize
    def __init__(self, *args, **kwargs):
        if getattr(self, "_picker_initialized", False):
            return

        _load_dut_bindings()
        self.dut = DutUnifiedBase(*args)
        self.xclock = xsp.XClock(self.dut.pxcStep, self.dut.pSelf)
        self.xport  = xsp.XPort()
        self.xclock.Add(self.xport)
        self.event = self.xclock.getEvent()
        self.internal_signals = {}
        self.xcfg = xsp.XSignalCFG(self.dut.GetXSignalCFGPath(), self.dut.GetXSignalCFGBasePtr())
        {% if __SIMULATOR__ == "gsim" %}
        # Set fast mode for GSim
        self.xclock.SetFastMode(xsp.FastMode_ONLY_STEP_RIS)
        {% endif %}

        # set output files
        if kwargs.get("waveform_filename"):
            self.dut.SetWaveform(kwargs.get("waveform_filename"))
        if kwargs.get("coverage_filename"):
            self.dut.SetCoverage(kwargs.get("coverage_filename"))

        # All pins
{{__XDATA_INIT__}}

        # BindDPI or Native pin address
{{__XDATA_BIND__}}

        # Add2Port
{{__XPORT_ADD__}}

        # Cascaded ports
{{__XPORT_CASCADED__}}

        self._picker_initialized = True
        self._picker_runtime_closed = False

    def __del__(self):
        if getattr(self, "_picker_shared_runtime", False):
            return
        self.Finish()

    ################################
    #         User APIs            #
    ################################
    def InitClock(self, name: str):
        self.xclock.Add(self.xport[name])

    def Step(self, i:int = 1):
        self.xclock.Step(i)

    def StepRis(self, callback, args=(), kwargs={}):
        self.xclock.StepRis(callback, args, kwargs)

    def StepFal(self, callback, args=(), kwargs={}):
        self.xclock.StepFal(callback, args, kwargs)

    def ResumeWaveformDump(self):
        return self.dut.ResumeWaveformDump()

    def PauseWaveformDump(self):
        return self.dut.PauseWaveformDump()

    def WaveformPaused(self) -> int:
        """ Returns 1 if waveform export is paused """
        return self.dut.WaveformPaused()

    def GetXPort(self):
        return self.xport

    def GetXClock(self):
        return self.xclock

    def SetWaveform(self, filename: str):
        self.dut.SetWaveform(filename)

    def GetWaveFormat(self) -> str:
        """
        Get the waveform extension, or an empty string if disabled.

        Returns:
            str: The extension of waveform file.
        """
        return self.dut.GetWaveFormat()

    def FlushWaveform(self):
        self.dut.FlushWaveform()

    def SetCoverage(self, filename: str):
        self.dut.SetCoverage(filename)

    def GetCovMetrics(self) -> int:
        """
        Get the bitmask for collected coverage metrics. 0 means coverage is disabled

        Returns:
            int: Collected coverage metrics bitmask:
                - Bit 0: line   (Line coverage)
                - Bit 1: cond   (Condition coverage)
                - Bit 2: fsm    (Finite-State Machine coverage)
                - Bit 3: toggle (Toggle coverage)
                - Bit 4: branch (Branch coverage)
                - Bit 5: assert (Assertion coverage)
        """
        return self.dut.GetCovMetrics()
    
    def CheckPoint(self, name: str) -> int:
        self.dut.CheckPoint(name)

    def Restore(self, name: str) -> int:
        self.dut.Restore(name)

    def GetInternalSignal(self, name: str, index=-1, is_array=False, use_vpi=False):
        if name not in self.internal_signals:
            signal = None
            if self.dut.GetXSignalCFGBasePtr() != 0 and not use_vpi:
                xname = "CFG:" + name
                if is_array:
                    assert index < 0, "Index is not supported for array signal"
                    signal = self.xcfg.NewXDataArray(name, xname)
                elif index >= 0:
                    signal = self.xcfg.NewXData(name, index, xname)
                else:
                    signal = self.xcfg.NewXData(name, xname)
            else:
                assert index < 0, "Index is not supported for VPI signal"
                assert not is_array, "Array is not supported for VPI signal"
                signal = xsp.XData.FromVPI(self.dut.GetVPIHandleObj(name),
                                           self.dut.GetVPIFuncPtr("vpi_get"),
                                           self.dut.GetVPIFuncPtr("vpi_get_value"),
                                           self.dut.GetVPIFuncPtr("vpi_put_value"), "VPI:" + name)
                if use_vpi:
                    assert signal is not None, f"Internal signal {name} not found (Check VPI is enabled)"
            if signal is None:
                return None
            if not isinstance(signal, xsp.XData):
                self.internal_signals[name] = [xsp.XPin(s, self.event) for s in signal]
            else:
                self.internal_signals[name] = xsp.XPin(signal, self.event)
        return self.internal_signals[name]

    def GetInternalSignalList(self, prefix="", deep=99, use_vpi=False):
        if self.dut.GetXSignalCFGBasePtr() != 0 and not use_vpi:
            return self.xcfg.GetSignalNames(prefix)
        else:
            return self.dut.VPIInternalSignalList(prefix, deep)

    def VPIInternalSignalList(self, prefix="", deep=99):
        return self.dut.VPIInternalSignalList(prefix, deep)

    def _finish_runtime(self):
        if getattr(self, "_picker_runtime_closed", False):
            return 0
        if hasattr(self, "dut"):
            self.dut.Finish()
        self._picker_runtime_closed = True
        self._picker_initialized = False
        if getattr(self, "_picker_shared_runtime", False) and type(self)._shared_instance is self:
            type(self)._shared_instance = None
        return 0

    def Finish(self):
        if getattr(self, "_picker_shared_runtime", False):
            return 0
        return self._finish_runtime()

    def Shutdown(self):
        return self._finish_runtime()

    def RefreshComb(self):
        self.dut.RefreshComb()

    def AtClone(self):
        """Re-init simulator state in child after fork."""
        return self.dut.atClone()

    ################################
    #      End of User APIs        #
    ################################

    def __getitem__(self, key):
        return xsp.XPin(self.port[key], self.event)

    # Async APIs wrapped from XClock
    async def AStep(self,i: int):
        return await self.xclock.AStep(i)

    async def ACondition(self,fc_cheker):
        return await self.xclock.ACondition(fc_cheker)

    def RunStep(self,i: int):
        return self.xclock.RunStep(i)

    def __setattr__(self, name, value):
        assert not isinstance(getattr(self, name, None),
                              (xsp.XPin, xsp.XData)), \
        f"XPin and XData of DUT are read-only, do you mean to set the value of the signal? please use `{name}.value = ` instead."
        return super().__setattr__(name, value)


if __name__=="__main__":
    dut=DUT{{__TOP_MODULE_NAME__}}()
    dut.Step(100)
