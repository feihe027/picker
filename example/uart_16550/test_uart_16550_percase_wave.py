#coding=utf8
"""Per-case waveform demo for uart_16550: one fsdb file per pytest case.

`dut.SetWaveform(name)` switches the fsdb dump to a new file at runtime, so an
autouse fixture gives every test case its own waveform. Requires a
waveform-enabled VCS export (`-w uart.fsdb`). conftest.py preloads the wrapper.
"""
import os

import pytest

from uart_16550 import DUTuart_16550

DIV1, LCR = 0x1C, 0x0C


@pytest.fixture(scope="module")
def dut():
    inst = DUTuart_16550()
    inst.InitClock("PCLK")
    yield inst
    inst.Finish()


@pytest.fixture(autouse=True)
def per_case_waveform(dut, request):
    dut.SetWaveform(request.node.name + ".fsdb")
    yield


def _reset(dut):
    dut.PSEL.value = 0
    dut.PENABLE.value = 0
    dut.PWRITE.value = 0
    dut.RXD.value = 1
    dut.PRESETn.value = 0
    dut.Step(6)
    dut.PRESETn.value = 1
    dut.Step(2)


def _write(dut, addr, data):
    dut.PSEL.value = 1
    dut.PWRITE.value = 1
    dut.PENABLE.value = 0
    dut.PADDR.value = addr
    dut.PWDATA.value = data & 0xFF
    dut.Step(1)
    dut.PENABLE.value = 1
    dut.Step(2)
    dut.PSEL.value = 0
    dut.PENABLE.value = 0
    dut.PWRITE.value = 0
    dut.Step(1)


def _read(dut, addr):
    dut.PSEL.value = 1
    dut.PWRITE.value = 0
    dut.PENABLE.value = 0
    dut.PADDR.value = addr
    dut.Step(1)
    dut.PENABLE.value = 1
    dut.Step(1)
    val = int(dut.PRDATA.value) & 0xFF
    dut.Step(1)
    dut.PSEL.value = 0
    dut.PENABLE.value = 0
    dut.Step(1)
    return val


def test_config_divisor(dut):
    _reset(dut)
    _write(dut, DIV1, 0x0C)
    assert _read(dut, DIV1) == 0x0C
    assert os.path.exists("test_config_divisor.fsdb")


def test_config_lcr(dut):
    _reset(dut)
    _write(dut, LCR, 0x1B)
    assert _read(dut, LCR) == 0x1B
    assert os.path.exists("test_config_lcr.fsdb")


def test_each_case_has_its_own_fsdb(dut):
    _reset(dut)
    _write(dut, DIV1, 0x22)
    dut.FlushWaveform()
    for name in ("test_config_divisor.fsdb", "test_config_lcr.fsdb"):
        assert os.path.exists(name), "missing per-case waveform %s" % name
        assert os.path.getsize(name) > 0, "empty per-case waveform %s" % name
