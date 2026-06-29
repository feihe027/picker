#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

require_cmd python3
require_cmd pytest

PICKER_BIN="$(resolve_picker)"
ROOT_DIR="${ROOT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/picker_vcs_runtime.XXXXXX")"
trap 'rm -rf "${TMP_DIR}"' EXIT

blue "[export-vcs-runtime] Exporting Adder.v to VCS Python template"
"${PICKER_BIN}" export \
  "${ROOT_DIR}/example/Adder/Adder.v" \
  --autobuild false \
  --sdir "${ROOT_DIR}/template" \
  --sname Adder \
  --tdir "${TMP_DIR}/Adder" \
  --lang python \
  --sim vcs \
  --wave_file_name runtime.fsdb

blue "[export-vcs-runtime] Validating generated VCS finish hook"
grep -q '\$fsdbDumpfile("runtime.fsdb")' "${TMP_DIR}/Adder/Adder_top.sv"
grep -q '\$fsdbDumpFinish;' "${TMP_DIR}/Adder/Adder_top.sv"
if grep -q '\$finish;' "${TMP_DIR}/Adder/Adder_top.sv"; then
  red "Unexpected \$finish in VCS-generated finish hook"
  exit 1
fi

blue "[export-vcs-runtime] Running pytest suite against generated wrapper"
PICKER_TEST_GENERATED_DUT="${TMP_DIR}/Adder/python/dut.py" \
PICKER_TEST_GENERATED_TOP_SV="${TMP_DIR}/Adder/Adder_top.sv" \
pytest -q "${ROOT_DIR}/test/pytest/export_adder_python_vcs_runtime"

green "[export-vcs-runtime] OK"
