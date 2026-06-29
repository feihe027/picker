#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

PICKER_BIN="$(resolve_picker)"
ROOT_DIR="${ROOT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/picker_finish_hooks.XXXXXX")"
trap 'rm -rf "${TMP_DIR}"' EXIT

assert_contains() {
  local file="$1"
  local pattern="$2"
  if ! grep -q -- "$pattern" "$file"; then
    red "Missing pattern '$pattern' in $file"
    exit 1
  fi
}

assert_not_contains() {
  local file="$1"
  local pattern="$2"
  if grep -q -- "$pattern" "$file"; then
    red "Unexpected pattern '$pattern' in $file"
    exit 1
  fi
}

blue "[export-finish-hooks] Exporting VCS wrapper with waveform"
"${PICKER_BIN}" export \
  "${ROOT_DIR}/example/Adder/Adder.v" \
  --autobuild false \
  --sdir "${ROOT_DIR}/template" \
  --sname Adder \
  --tdir "${TMP_DIR}/vcs" \
  --lang python \
  --sim vcs \
  --wave_file_name runtime.fsdb

assert_contains "${TMP_DIR}/vcs/Adder_top.sv" '\$fsdbDumpfile("runtime.fsdb")'
assert_contains "${TMP_DIR}/vcs/Adder_top.sv" '\$fsdbDumpFinish;'
assert_not_contains "${TMP_DIR}/vcs/Adder_top.sv" '\$finish;'

blue "[export-finish-hooks] Exporting VCS wrapper without waveform"
"${PICKER_BIN}" export \
  "${ROOT_DIR}/example/Adder/Adder.v" \
  --autobuild false \
  --sdir "${ROOT_DIR}/template" \
  --sname Adder \
  --tdir "${TMP_DIR}/vcs_nowave" \
  --lang python \
  --sim vcs

assert_contains "${TMP_DIR}/vcs_nowave/Adder_top.sv" 'function void finish_'
assert_not_contains "${TMP_DIR}/vcs_nowave/Adder_top.sv" '\$fsdbDumpFinish;'
assert_not_contains "${TMP_DIR}/vcs_nowave/Adder_top.sv" '\$finish;'

blue "[export-finish-hooks] Exporting UVS wrapper with waveform"
"${PICKER_BIN}" export \
  "${ROOT_DIR}/example/Adder/Adder.v" \
  --autobuild false \
  --sdir "${ROOT_DIR}/template" \
  --sname Adder \
  --tdir "${TMP_DIR}/uvs" \
  --lang python \
  --sim uvs \
  --wave_file_name runtime.usdb

assert_contains "${TMP_DIR}/uvs/Adder_top.sv" '\$usdbDumpfile("runtime.usdb")'
assert_contains "${TMP_DIR}/uvs/Adder_top.sv" '\$usdbDumpFinish;'
assert_not_contains "${TMP_DIR}/uvs/Adder_top.sv" '\$finish;'

blue "[export-finish-hooks] Exporting Verilator wrapper with waveform"
"${PICKER_BIN}" export \
  "${ROOT_DIR}/example/Adder/Adder.v" \
  --autobuild false \
  --sdir "${ROOT_DIR}/template" \
  --sname Adder \
  --tdir "${TMP_DIR}/verilator" \
  --lang python \
  --sim verilator \
  --wave_file_name runtime.vcd

assert_contains "${TMP_DIR}/verilator/Adder_top.sv" '\$dumpfile("runtime.vcd")'
assert_contains "${TMP_DIR}/verilator/Adder_top.sv" '\$finish;'
assert_not_contains "${TMP_DIR}/verilator/Adder_top.sv" 'DumpFinish'

green "[export-finish-hooks] OK"
