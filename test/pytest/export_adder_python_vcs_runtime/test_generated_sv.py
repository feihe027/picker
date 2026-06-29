def test_generated_vcs_top_uses_fsdb_finish_hook(generated_top_sv_path):
    content = generated_top_sv_path.read_text(encoding="utf-8")

    assert '$fsdbDumpfile("runtime.fsdb")' in content
    assert "$fsdbDumpFinish;" in content
    assert "$finish;" not in content


def test_generated_vcs_top_exports_finish_function(generated_top_sv_path):
    content = generated_top_sv_path.read_text(encoding="utf-8")

    assert 'export "DPI-C" function finish_' in content
    assert "function void finish_" in content
    assert "$usdbDumpFinish;" not in content
