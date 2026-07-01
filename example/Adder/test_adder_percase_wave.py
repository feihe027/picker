#coding=utf8
"""Per-case waveform demo for the Adder: one fsdb file per pytest case.

VCS dumps a single continuous fsdb by default. `dut.SetWaveform(name)` switches
the dump to a new file at runtime (it closes the current fsdb and opens a fresh
one), so an autouse fixture can give every test case its own waveform — handy
for inspecting exactly the case that failed.

Requires a waveform-enabled VCS export, e.g.:

    picker export example/Adder/Adder.v --sim vcs -w Adder.fsdb \\
        --sname Adder --tdir picker_out_adder/Adder --sdir template --lang python

Run with the wrapper preloaded (conftest.py does it, or set LD_PRELOAD).
"""
import os

import pytest

from Adder import DUTAdder

MASK_128 = (1 << 128) - 1


@pytest.fixture(scope="module")
def dut():
    instance = DUTAdder()
    yield instance
    instance.Finish()


@pytest.fixture(autouse=True)
def per_case_waveform(dut, request):
    """Switch to a per-test fsdb before each case runs."""
    dut.SetWaveform(request.node.name + ".fsdb")
    yield


def _apply(dut, a, b, cin):
    dut.a.value = a
    dut.b.value = b
    dut.cin.value = cin
    dut.Step(1)
    return dut.sum.value, dut.cout.value


def test_simple_add(dut):
    s, c = _apply(dut, 1, 2, 0)
    assert s == 3 and c == 0
    assert os.path.exists("test_simple_add.fsdb")


def test_carry_out(dut):
    s, c = _apply(dut, MASK_128, 1, 0)
    assert s == 0 and c == 1
    assert os.path.exists("test_carry_out.fsdb")


def test_each_case_has_its_own_fsdb(dut):
    _apply(dut, 7, 8, 1)
    dut.FlushWaveform()
    # The two earlier cases each left a non-empty, distinct waveform file.
    for name in ("test_simple_add.fsdb", "test_carry_out.fsdb"):
        assert os.path.exists(name), "missing per-case waveform %s" % name
        assert os.path.getsize(name) > 0, "empty per-case waveform %s" % name
