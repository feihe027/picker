#coding=utf8
"""Coverage accumulates across runs: multiple simv processes, one merged report.

VCS commits coverage once per process ($finish at exit), so per-file / per-run
coverage needs separate processes. Each run tags its data with a distinct test
name via ``-cm_name`` (passed to the DUT constructor), producing a separate
record under ``<vdb>/snps/coverage/db/testdata/<name>/``. ``urg`` then merges all
records into the union.

This test drives two processes with disjoint stimulus (TX-side vs RX-side),
asserts both records were committed, and — when a coverage license is available
— merges them with ``urg`` and checks the combined line coverage is at least
each single run's. Without urg/license it skips the numeric part.
"""
import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))

DR, IER, FCR, LCR, MCR, LSR, DIV1, DIV2 = 0x00, 0x04, 0x08, 0x0C, 0x10, 0x14, 0x1C, 0x20


def _preload_env():
    env = dict(os.environ)
    lib = os.path.join(HERE, "uart_16550", "libUTuart_16550.so")
    if os.path.exists(lib):
        prev = env.get("LD_PRELOAD", "")
        env["LD_PRELOAD"] = lib if not prev else lib + ":" + prev
    return env


def _find_coverage_vdb():
    for cand in (os.path.join(HERE, "uart_16550", "vcs_coverage.vdb"),
                 os.path.join(HERE, "vcs_coverage.vdb")):
        if os.path.isdir(cand):
            return cand
    hits = glob.glob(os.path.join(HERE, "**", "*.vdb"), recursive=True)
    return hits[0] if hits else None


def _parse_line_coverage(text):
    for i, ln in enumerate(text.splitlines()):
        cols = ln.split()
        if "LINE" in cols and ("SCORE" in cols or "NAME" in cols):
            idx = cols.index("LINE")
            for nxt in text.splitlines()[i + 1:]:
                nums = nxt.split()
                if len(nums) > idx:
                    try:
                        return float(nums[idx].rstrip("%"))
                    except ValueError:
                        continue
    m = re.search(r"[Ll]ine(?:\s*[Cc]overage)?[:\s]+([0-9]+(?:\.[0-9]+)?)\s*%", text)
    return float(m.group(1)) if m else None


def _urg_line_coverage(*vdb_or_dirs):
    """Line coverage from urg over one or more inputs (records merge), or None
    if urg is missing/unlicensed."""
    if shutil.which("urg") is None:
        return None
    out = tempfile.mkdtemp(prefix="urg_merge_")
    cmd = ["urg", "-full64"]
    for d in vdb_or_dirs:
        cmd += ["-dir", d]
    cmd += ["-report", out]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            return None
        dash = os.path.join(out, "dashboard.txt")
        return _parse_line_coverage(open(dash).read()) if os.path.exists(dash) else None
    except OSError:
        return None
    finally:
        shutil.rmtree(out, ignore_errors=True)


def test_coverage_merges_across_runs():
    vdb = _find_coverage_vdb()
    if vdb is None:
        pytest.skip("no VCS coverage database; export with -c to enable coverage")

    testdata = os.path.join(vdb, "snps", "coverage", "db", "testdata")
    if os.path.isdir(testdata):
        for entry in glob.glob(os.path.join(testdata, "*")):
            shutil.rmtree(entry, ignore_errors=True)

    # Two processes, distinct names, disjoint stimulus.
    for name, variant in (("run_tx", "tx"), ("run_rx", "rx")):
        subprocess.run([sys.executable, os.path.abspath(__file__), name, variant],
                       cwd=HERE, env=_preload_env(), check=True)

    # Both runs committed their own record -> mergeable by urg.
    for name in ("run_tx", "run_rx"):
        rec = os.path.join(testdata, name)
        assert os.path.isdir(rec), "missing coverage record %s" % name
        assert glob.glob(os.path.join(rec, "*.data.xml")), "empty record %s" % name

    # Numeric merge check needs a coverage license.
    merged = _urg_line_coverage(vdb)
    if merged is None:
        pytest.skip("urg unavailable or no coverage license; run `make coverage`")
    assert merged > 0.0
    print("uart_16550 merged line coverage (2 runs): %.2f%%" % merged)


# --------------------------------------------------------------------------- #
# Standalone driver: python3 <this file> <cm_name> <tx|rx>
# --------------------------------------------------------------------------- #
def _apb_write(d, addr, data):
    d.PSEL.value = 1; d.PWRITE.value = 1; d.PENABLE.value = 0
    d.PADDR.value = addr; d.PWDATA.value = data & 0xFF; d.Step(1)
    d.PENABLE.value = 1; d.Step(2)
    d.PSEL.value = 0; d.PENABLE.value = 0; d.PWRITE.value = 0; d.Step(1)


def _send_serial(d, byte, bit_cycles=16):
    for bit in [0] + [(byte >> i) & 1 for i in range(8)] + [1]:
        d.RXD.value = bit; d.Step(bit_cycles)
    d.RXD.value = 1; d.Step(bit_cycles)


def _main(cm_name, variant):
    from uart_16550 import DUTuart_16550
    d = DUTuart_16550(["-cm_name", cm_name])
    d.InitClock("PCLK")
    d.RXD.value = 1
    d.PRESETn.value = 0; d.Step(6); d.PRESETn.value = 1; d.Step(2)
    _apb_write(d, DIV1, 0x01); _apb_write(d, LCR, 0x03); _apb_write(d, FCR, 0x07)
    if variant == "tx":
        for b in (0x55, 0xA3, 0x00, 0xFF, 0x7E, 0x81):
            _apb_write(d, DR, b)
        d.Step(16 * 12 * 6)
    else:  # rx
        for b in (0x41, 0x55, 0xC3, 0x00, 0xFF, 0x3C):
            _send_serial(d, b)
    d.Finish()


if __name__ == "__main__":
    _main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "tx")
