from importlib import import_module

def _load_dut_module():
    last_error = None
    for module_name in ("UT_{{__TOP_MODULE_NAME__}}", "{{__TOP_MODULE_NAME__}}", "__init__"):
        try:
            module = import_module(module_name)
        except ModuleNotFoundError as exc:
            if exc.name != module_name:
                raise
            last_error = exc
            continue
        try:
            getattr(module, "DUT{{__TOP_MODULE_NAME__}}")
            return module
        except AttributeError as exc:
            last_error = exc
    raise ImportError("Failed to import DUT{{__TOP_MODULE_NAME__}}") from last_error


_DUT_MODULE = _load_dut_module()
if __name__ == "__main__":
    _DUT_MODULE.restart_with_preload()

_DUT_MODULE._load_dut_bindings()
globals().update({name: value for name, value in vars(_DUT_MODULE).items() if not name.startswith("_")})
DUT{{__TOP_MODULE_NAME__}} = _DUT_MODULE.DUT{{__TOP_MODULE_NAME__}}


if __name__ == "__main__":
    dut = DUT{{__TOP_MODULE_NAME__}}()
    # dut.InitClock("clk")

    dut.Step(1)

    dut.Finish()
