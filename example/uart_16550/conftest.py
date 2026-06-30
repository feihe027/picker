#coding=utf8
"""Pytest collection hook for the VCS/UVS uart_16550 example.

VCS/UVS load the simulator as a shared library into this process. The wrapper
needs the simulator runtime preloaded (otherwise importing the bindings fails
with "cannot allocate memory in static TLS block"). ``restart_with_preload()``
re-execs the interpreter once with ``LD_PRELOAD`` set; it is a no-op after the
first call and on non-VCS/UVS builds, so it is safe to call unconditionally
here, before any test instantiates the DUT.

Alternatively skip this file and run with the library preloaded yourself:

    LD_PRELOAD=./uart_16550/libUTuart_16550.so python3 -m pytest
"""
import uart_16550


def pytest_configure(config):
    uart_16550.restart_with_preload()
