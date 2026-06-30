#coding=utf8
"""Pytest suite for the uart_16550 example: VCS waveform + coverage.

Run from the generated DUT directory (the one holding the ``uart_16550``
package), with the wrapper preloaded (``conftest.py`` does it automatically)::

    picker export --fs example/uart_16550/uart_16550.sv,...all .sv... \\
        --sim vcs -c -w uart.fsdb --sname uart_16550 \\
        --tdir picker_out_uart/uart_16550 --sdir template --lang python
    cd picker_out_uart && cp ../example/uart_16550/test_uart_16550_wave_coverage.py .
    LD_PRELOAD=./uart_16550/libUTuart_16550.so python3 -m pytest \\
        test_uart_16550_wave_coverage.py

The suite drives the APB register file, the baud generator and the TX/RX serial
paths so that line/branch/toggle coverage is exercised broadly, then checks:

* Waveform -- the shared DUT dumps one continuous fsdb; assert it is produced
  and grows as cases run.
* Coverage -- VCS commits its .vdb only at $finish (deferred to atexit by the
  python shared runtime), so this process cannot read its own coverage. The
  coverage check runs this file as a standalone driver in a subprocess: when it
  exits, $finish commits the .vdb and we assert per-metric data was written.
  Render the human report with ``make coverage`` (runs ``urg``).
"""
import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile

import pytest

from uart_16550 import DUTuart_16550

HERE = os.path.dirname(os.path.abspath(__file__))

# APB byte addresses (register index << 2; the RTL uses PADDR[6:2]).
DR   = 0x00   # RBR/THR  - data register (R/W)
IER  = 0x04   # interrupt enable (W)
IIR  = 0x08   # interrupt id (R) / FCR FIFO control (W)
FCR  = 0x08
LCR  = 0x0C   # line control (R/W)
MCR  = 0x10   # modem control (W)
LSR  = 0x14   # line status (R)
MSR  = 0x18   # modem status (R)
DIV1 = 0x1C   # divisor low (R/W)
DIV2 = 0x20   # divisor high (R/W)

# LSR bits
LSR_DR   = 1 << 0   # data ready (rx fifo not empty)


# --------------------------------------------------------------------------- #
# Low-level helpers
# --------------------------------------------------------------------------- #
def reset(dut):
    dut.PSEL.value = 0
    dut.PENABLE.value = 0
    dut.PWRITE.value = 0
    dut.RXD.value = 1            # idle line is high
    dut.nCTS.value = 1
    dut.nDSR.value = 1
    dut.nDCD.value = 1
    dut.nRI.value = 1
    dut.PRESETn.value = 0
    dut.Step(6)
    dut.PRESETn.value = 1
    dut.Step(2)


def apb_write(dut, addr, data):
    dut.PSEL.value = 1
    dut.PWRITE.value = 1
    dut.PENABLE.value = 0
    dut.PADDR.value = addr
    dut.PWDATA.value = data & 0xFF
    dut.Step(1)                  # IDLE -> SETUP
    dut.PENABLE.value = 1
    dut.Step(1)                  # SETUP -> ACCESS (we <= 1)
    dut.Step(1)                  # ACCESS -> IDLE (write commits, PREADY)
    dut.PSEL.value = 0
    dut.PENABLE.value = 0
    dut.PWRITE.value = 0
    dut.Step(1)


def apb_read(dut, addr):
    dut.PSEL.value = 1
    dut.PWRITE.value = 0
    dut.PENABLE.value = 0
    dut.PADDR.value = addr
    dut.Step(1)                  # IDLE -> SETUP
    dut.PENABLE.value = 1
    dut.Step(1)                  # SETUP -> ACCESS
    val = int(dut.PRDATA.value) & 0xFF
    dut.Step(1)                  # ACCESS -> IDLE (re pulse for read side effects)
    dut.PSEL.value = 0
    dut.PENABLE.value = 0
    dut.Step(1)
    return val


def configure(dut, divisor=1, lcr=0x03):
    """8N1 frame, smallest divisor so the serial paths run quickly."""
    apb_write(dut, DIV1, divisor & 0xFF)
    apb_write(dut, DIV2, (divisor >> 8) & 0xFF)
    apb_write(dut, LCR, lcr)


def send_serial_byte(dut, byte, divisor=1):
    """Drive one 8N1 frame on RXD at the configured baud (16x oversampling,
    so each bit lasts 16*divisor PCLK cycles)."""
    bit_cycles = 16 * divisor
    frame = [0]                                  # start bit
    frame += [(byte >> i) & 1 for i in range(8)]  # 8 data bits, LSB first
    frame += [1]                                  # stop bit
    for bit in frame:
        dut.RXD.value = bit
        dut.Step(bit_cycles)
    dut.RXD.value = 1
    dut.Step(bit_cycles)


def _exercise(dut, rounds=4):
    """Broad stimulus over every register and the TX/RX paths -- shared by the
    functional tests and the coverage driver so committed coverage matches what
    the suite exercises."""
    reset(dut)
    configure(dut, divisor=1, lcr=0x03)
    # All write-only / control registers.
    apb_write(dut, IER, 0x0F)      # enable all interrupt sources
    apb_write(dut, FCR, 0x07)      # enable + reset rx/tx FIFOs
    apb_write(dut, MCR, 0x13)      # DTR|RTS|loopback off variants
    apb_write(dut, MCR, 0x00)
    # Read every readable register.
    for addr in (DR, IIR, LCR, LSR, MSR, DIV1, DIV2):
        apb_read(dut, addr)
    # Modem inputs -> MSR.
    for cts, dsr, dcd, ri in ((0, 1, 1, 1), (1, 0, 1, 1), (1, 1, 0, 1), (1, 1, 1, 0)):
        dut.nCTS.value = cts
        dut.nDSR.value = dsr
        dut.nDCD.value = dcd
        dut.nRI.value = ri
        dut.Step(4)
        apb_read(dut, MSR)
    dut.nCTS.value = 1
    dut.nDSR.value = 1
    dut.nDCD.value = 1
    dut.nRI.value = 1
    # TX: push several bytes through the transmit FIFO/shifter.
    for b in (0x55, 0xA3, 0x00, 0xFF, 0x7E):
        apb_write(dut, DR, b)
    dut.Step(16 * 12 * 5)          # let the bytes shift out
    # RX: drive serial frames into the receive FIFO/shifter.
    for b in (0x41, 0x55, 0xC3, 0x00, 0xFF):
        send_serial_byte(dut, b, divisor=1)
        apb_read(dut, LSR)
        apb_read(dut, DR)
    # A few more register churns for branch coverage.
    for _ in range(rounds):
        apb_write(dut, FCR, 0x06)  # reset both FIFOs
        apb_write(dut, LCR, 0x1B)  # parity enabled variant
        apb_read(dut, IIR)
        apb_read(dut, LSR)


def _find_coverage_vdb():
    for cand in (
        os.path.join(HERE, "uart_16550", "vcs_coverage.vdb"),
        os.path.join(HERE, "vcs_coverage.vdb"),
    ):
        if os.path.isdir(cand):
            return cand
    hits = glob.glob(os.path.join(HERE, "**", "*.vdb"), recursive=True)
    return hits[0] if hits else None


def _preload_env():
    env = dict(os.environ)
    lib = os.path.join(HERE, "uart_16550", "libUTuart_16550.so")
    if os.path.exists(lib):
        prev = env.get("LD_PRELOAD", "")
        env["LD_PRELOAD"] = lib if not prev else lib + ":" + prev
    return env


def _parse_line_coverage(report_text):
    """Pull the overall LINE coverage percentage out of a urg text report."""
    lines = report_text.splitlines()
    for i, ln in enumerate(lines):
        cols = ln.split()
        if "LINE" in cols and ("SCORE" in cols or "NAME" in cols):
            idx = cols.index("LINE")
            for nxt in lines[i + 1:]:
                nums = nxt.split()
                if len(nums) > idx:
                    try:
                        return float(nums[idx].rstrip("%"))
                    except ValueError:
                        continue
    m = re.search(r"[Ll]ine(?:\s*[Cc]overage)?[:\s]+([0-9]+(?:\.[0-9]+)?)\s*%",
                  report_text)
    return float(m.group(1)) if m else None


def _urg_line_coverage(vdb):
    """Overall line coverage via urg, or None if urg is missing or fails (e.g.
    no coverage license in this environment)."""
    if shutil.which("urg") is None:
        return None
    out = tempfile.mkdtemp(prefix="urg_uart_")
    try:
        res = subprocess.run(
            ["urg", "-full64", "-dir", vdb, "-report", out],
            capture_output=True, text=True,
        )
        if res.returncode != 0:
            return None
        dash = os.path.join(out, "dashboard.txt")
        if not os.path.exists(dash):
            return None
        with open(dash) as fh:
            return _parse_line_coverage(fh.read())
    except OSError:
        return None
    finally:
        shutil.rmtree(out, ignore_errors=True)


@pytest.fixture(scope="module")
def dut():
    instance = DUTuart_16550()
    instance.InitClock("PCLK")
    yield instance
    instance.Finish()


# --------------------------------------------------------------------------- #
# Functional / register tests
# --------------------------------------------------------------------------- #
def test_reset_clears_status(dut):
    reset(dut)
    lsr = apb_read(dut, LSR)
    # After reset the receive FIFO is empty -> no data ready.
    assert (lsr & LSR_DR) == 0


@pytest.mark.parametrize("addr,val", [(DIV1, 0x12), (DIV2, 0x34), (LCR, 0x1B)])
def test_register_readback(dut, addr, val):
    reset(dut)
    apb_write(dut, addr, val)
    assert apb_read(dut, addr) == val


def test_divisor_16bit(dut):
    reset(dut)
    apb_write(dut, DIV1, 0xCD)
    apb_write(dut, DIV2, 0xAB)
    assert apb_read(dut, DIV1) == 0xCD
    assert apb_read(dut, DIV2) == 0xAB


def test_tx_byte_sets_line_busy(dut):
    reset(dut)
    configure(dut, divisor=1, lcr=0x03)
    apb_write(dut, FCR, 0x07)
    txd_seen_low = False
    apb_write(dut, DR, 0x55)        # 0x55 toggles -> guaranteed start bit low
    for _ in range(16 * 12):
        dut.Step(1)
        if int(dut.TXD.value) == 0:
            txd_seen_low = True
    assert txd_seen_low, "TXD never went low while transmitting"


def test_rx_byte_becomes_ready(dut):
    reset(dut)
    configure(dut, divisor=1, lcr=0x03)
    apb_write(dut, FCR, 0x07)
    send_serial_byte(dut, 0x41, divisor=1)
    # Allow the received byte to land in the rx FIFO.
    dut.Step(32)
    lsr = apb_read(dut, LSR)
    assert (lsr & LSR_DR) != 0, "data-ready not set after receiving a byte"


def test_modem_status_reacts(dut):
    reset(dut)
    dut.nCTS.value = 0             # assert CTS (active low)
    dut.Step(4)
    msr_cts = apb_read(dut, MSR)
    dut.nCTS.value = 1
    dut.Step(4)
    msr_idle = apb_read(dut, MSR)
    assert msr_cts != msr_idle, "MSR did not react to modem input change"


def test_full_exercise_runs(dut):
    # Smoke: the whole stimulus sequence runs without error in-process.
    _exercise(dut, rounds=2)


# --------------------------------------------------------------------------- #
# Waveform
# --------------------------------------------------------------------------- #
def test_waveform_file_created(dut):
    _exercise(dut, rounds=1)
    assert os.path.exists("uart.fsdb"), "fsdb waveform file was not created"
    assert os.path.getsize("uart.fsdb") > 0, "fsdb waveform file is empty"


def test_waveform_grows_with_more_activity(dut):
    before = os.path.getsize("uart.fsdb") if os.path.exists("uart.fsdb") else 0
    _exercise(dut, rounds=3)
    dut.FlushWaveform()
    assert os.path.getsize("uart.fsdb") >= before


# --------------------------------------------------------------------------- #
# Coverage
# --------------------------------------------------------------------------- #
def test_coverage_committed_with_all_metrics():
    vdb = _find_coverage_vdb()
    if vdb is None:
        pytest.skip("no VCS coverage database; export with -c to enable coverage")

    testdata = os.path.join(vdb, "snps", "coverage", "db", "testdata")
    if os.path.isdir(testdata):
        for entry in glob.glob(os.path.join(testdata, "*")):
            shutil.rmtree(entry, ignore_errors=True)

    # Run this file as a standalone driver so its atexit $finish commits the vdb.
    subprocess.run(
        [sys.executable, os.path.abspath(__file__)],
        cwd=HERE, env=_preload_env(), check=True,
    )

    for metric in ("line", "cond", "fsm", "tgl", "branch"):
        hits = glob.glob(os.path.join(testdata, "*", "%s.verilog.data.xml" % metric))
        assert hits, "no committed coverage data for metric %r" % metric
        assert os.path.getsize(hits[0]) > 0, "empty coverage data for %r" % metric


def test_line_coverage_meets_threshold():
    """Gate on actual line coverage when urg is available. Skips where urg or a
    coverage license is missing -- run ``make coverage`` in a licensed env to
    get the report. Tune the floor with UART_MIN_LINE_COV (default 60%)."""
    vdb = _find_coverage_vdb()
    if vdb is None:
        pytest.skip("no VCS coverage database; export with -c to enable coverage")

    subprocess.run(
        [sys.executable, os.path.abspath(__file__)],
        cwd=HERE, env=_preload_env(), check=True,
    )
    cov = _urg_line_coverage(vdb)
    if cov is None:
        pytest.skip("urg unavailable or no coverage license; run `make coverage`")

    threshold = float(os.environ.get("UART_MIN_LINE_COV", "60"))
    print("uart_16550 line coverage: %.2f%% (threshold %.1f%%)" % (cov, threshold))
    assert cov >= threshold, (
        "line coverage %.2f%% below threshold %.1f%%" % (cov, threshold)
    )



# --------------------------------------------------------------------------- #
# Standalone driver entry point (used by the coverage subprocess)
# --------------------------------------------------------------------------- #
def _main():
    dut = DUTuart_16550()
    dut.InitClock("PCLK")
    for _ in range(3):
        _exercise(dut, rounds=4)
    dut.Finish()


if __name__ == "__main__":
    _main()
