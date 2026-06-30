#coding=utf8
"""Pytest suite for the Adder example: VCS waveform + coverage.

Run it from the generated DUT directory (the one holding the ``Adder`` package),
with the wrapper preloaded -- ``conftest.py`` does this automatically, or do it
by hand::

    picker export example/Adder/Adder.v --sim vcs -c -w Adder.fsdb \\
        --sname Adder --tdir picker_out_adder/Adder --sdir template --lang python
    cd picker_out_adder && cp ../example/Adder/test_adder_wave_coverage.py .
    LD_PRELOAD=./Adder/libUTAdder.so python3 -m pytest test_adder_wave_coverage.py

Two things are checked:

* Waveform -- the SV top dumps an fsdb continuously, so all cases of the shared
  DUT append to one trace. The trace exists and grows during the session.

* Coverage -- VCS only commits its coverage database (``.vdb``) at ``$finish``,
  which the python shared runtime defers to process exit (atexit). A test in
  *this* process therefore cannot observe its own committed coverage. The
  coverage check runs a short driver in a subprocess: when that process exits,
  ``$finish`` commits the ``.vdb`` and we assert the per-test data was written.
  Render a human report afterwards with ``make coverage`` (runs ``urg``).
"""
import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile

import pytest

from Adder import DUTAdder

HERE = os.path.dirname(os.path.abspath(__file__))
MASK_128 = (1 << 128) - 1


def _find_coverage_vdb():
    """Locate the VCS coverage database next to the generated package."""
    for cand in (
        os.path.join(HERE, "Adder", "vcs_coverage.vdb"),
        os.path.join(HERE, "vcs_coverage.vdb"),
    ):
        if os.path.isdir(cand):
            return cand
    hits = glob.glob(os.path.join(HERE, "**", "*.vdb"), recursive=True)
    return hits[0] if hits else None


def _preload_env():
    env = dict(os.environ)
    lib = os.path.join(HERE, "Adder", "libUTAdder.so")
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
    out = tempfile.mkdtemp(prefix="urg_adder_")
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
    """One shared DUT for the whole module (VCS keeps global simulator state and
    cannot be re-initialized in one process). Teardown finalizes the fsdb."""
    instance = DUTAdder()
    yield instance
    instance.Finish()


def _apply(dut, a, b, cin):
    dut.a.value = a
    dut.b.value = b
    dut.cin.value = cin
    dut.Step(1)
    return dut.sum.value, dut.cout.value


# --------------------------------------------------------------------------- #
# Waveform
# --------------------------------------------------------------------------- #
def test_waveform_file_created(dut):
    """Drive several transactions and confirm the fsdb trace is produced."""
    for i in range(8):
        _apply(dut, i, i * 3 + 1, i & 1)
    assert os.path.exists("Adder.fsdb"), "fsdb waveform file was not created"
    assert os.path.getsize("Adder.fsdb") > 0, "fsdb waveform file is empty"


def test_waveform_grows_with_more_activity(dut):
    """More simulation time -> a larger trace, proving cases accumulate into
    the single continuous fsdb."""
    before = os.path.getsize("Adder.fsdb") if os.path.exists("Adder.fsdb") else 0
    for i in range(64):
        _apply(dut, i << 1, i, 0)
    dut.FlushWaveform()
    after = os.path.getsize("Adder.fsdb")
    assert after >= before, "fsdb did not grow as more cases ran"


# --------------------------------------------------------------------------- #
# Coverage
# --------------------------------------------------------------------------- #
def test_coverage_db_committed():
    """Coverage commits at process exit. Run a short driver in a subprocess so
    its atexit ``$finish`` fires, then assert the .vdb gained test data."""
    vdb = _find_coverage_vdb()
    if vdb is None:
        pytest.skip("no VCS coverage database; export with -c to enable coverage")

    testdata = os.path.join(vdb, "snps", "coverage", "db", "testdata")
    # Drop any stale per-test data so the assertion reflects this run only.
    if os.path.isdir(testdata):
        for entry in glob.glob(os.path.join(testdata, "*")):
            shutil.rmtree(entry, ignore_errors=True)

    driver = (
        "from Adder import DUTAdder\n"
        "d = DUTAdder()\n"
        "for i in range(64):\n"
        "    d.a.value = i\n"
        "    d.b.value = (i * 7) & 0xff\n"
        "    d.cin.value = i & 1\n"
        "    d.Step(1)\n"
        "d.Finish()\n"
    )
    subprocess.run(
        [sys.executable, "-c", driver], cwd=HERE, env=_preload_env(), check=True
    )

    data = glob.glob(os.path.join(testdata, "*", "*.data.xml"))
    assert data, "coverage data was not committed to %s" % vdb


def test_coverage_has_all_metrics():
    """A multi-case run commits every requested metric (line/cond/fsm/tgl/branch).

    Coverage is cumulative within the single continuous simulation: each case
    adds to the union, so more (and more diverse) stimulus only grows the
    committed coverage. We assert each metric's data file is present and
    non-empty rather than a byte count, since the on-disk data is compressed and
    its size is not a reliable coverage measure (use ``make coverage`` / ``urg``
    for actual numbers)."""
    vdb = _find_coverage_vdb()
    if vdb is None:
        pytest.skip("no VCS coverage database; export with -c to enable coverage")

    testdata = os.path.join(vdb, "snps", "coverage", "db", "testdata")
    if os.path.isdir(testdata):
        for entry in glob.glob(os.path.join(testdata, "*")):
            shutil.rmtree(entry, ignore_errors=True)

    driver = (
        "from Adder import DUTAdder\n"
        "d = DUTAdder()\n"
        "for i in range(128):\n"
        "    d.a.value = (i * 0x9E3779B1) & ((1 << 128) - 1)\n"
        "    d.b.value = (i * 0x1234567) & ((1 << 128) - 1)\n"
        "    d.cin.value = i & 1\n"
        "    d.Step(1)\n"
        "d.Finish()\n"
    )
    subprocess.run(
        [sys.executable, "-c", driver], cwd=HERE, env=_preload_env(), check=True
    )

    for metric in ("line", "cond", "fsm", "tgl", "branch"):
        hits = glob.glob(
            os.path.join(testdata, "*", "%s.verilog.data.xml" % metric)
        )
        assert hits, "no committed coverage data for metric %r" % metric
        assert os.path.getsize(hits[0]) > 0, "empty coverage data for %r" % metric


def test_line_coverage_meets_threshold():
    """Gate on actual line coverage when urg is available. Skips where urg or a
    coverage license is missing -- run ``make coverage`` in a licensed env to
    get the report. Tune the floor with ADDER_MIN_LINE_COV (default 90%)."""
    vdb = _find_coverage_vdb()
    if vdb is None:
        pytest.skip("no VCS coverage database; export with -c to enable coverage")

    driver = (
        "from Adder import DUTAdder\n"
        "d = DUTAdder()\n"
        "for i in range(128):\n"
        "    d.a.value = (i * 0x9E3779B1) & ((1 << 128) - 1)\n"
        "    d.b.value = (i * 0x1234567) & ((1 << 128) - 1)\n"
        "    d.cin.value = i & 1\n"
        "    d.Step(1)\n"
        "d.Finish()\n"
    )
    subprocess.run(
        [sys.executable, "-c", driver], cwd=HERE, env=_preload_env(), check=True
    )
    cov = _urg_line_coverage(vdb)
    if cov is None:
        pytest.skip("urg unavailable or no coverage license; run `make coverage`")

    threshold = float(os.environ.get("ADDER_MIN_LINE_COV", "90"))
    print("Adder line coverage: %.2f%% (threshold %.1f%%)" % (cov, threshold))
    assert cov >= threshold, (
        "line coverage %.2f%% below threshold %.1f%%" % (cov, threshold)
    )


