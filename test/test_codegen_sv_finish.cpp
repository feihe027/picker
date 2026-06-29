#include <cassert>
#include <string>
#include <vector>

#include "codegen/sv.hpp"

bool picker::is_debug = false;
char *picker::lib_random_hash = const_cast<char *>("H");

static bool contains_line(const std::string &haystack, const std::string &needle)
{
    return haystack.find(needle) != std::string::npos;
}

static std::string render_extend_sv(const std::string &simulator, const std::string &wave_file_name)
{
    nlohmann::json data;
    data["__TOP_MODULE_NAME__"] = "Top";

    picker::sv_module_define mod;
    mod.module_name = "dut";
    mod.module_nums = 1;
    mod.pins.push_back({"clk", "input", -1, 0});

    std::vector<picker::sv_module_define> modules{mod};
    std::vector<picker::sv_signal_define> internal;

    nlohmann::json signal_tree;
    picker::codegen::gen_sv_param(
        data,
        modules,
        internal,
        signal_tree,
        wave_file_name,
        simulator,
        picker::SignalAccessType::DPI
    );

    return data["__EXTEND_SV__"].get<std::string>();
}

int main()
{
    const auto verilator_extend = render_extend_sv("verilator", "wave.vcd");
    assert(contains_line(verilator_extend, "finish_H"));
    assert(contains_line(verilator_extend, "$finish;"));
    assert(!contains_line(verilator_extend, "DumpFinish"));

    const auto vcs_extend = render_extend_sv("vcs", "wave.fsdb");
    assert(contains_line(vcs_extend, "$fsdbDumpFinish;"));
    assert(!contains_line(vcs_extend, "$finish;"));

    const auto vcs_no_wave_extend = render_extend_sv("vcs", "");
    assert(contains_line(vcs_no_wave_extend, "function void finish_H;"));
    assert(!contains_line(vcs_no_wave_extend, "$fsdbDumpFinish;"));
    assert(!contains_line(vcs_no_wave_extend, "$finish;"));

    const auto uvs_extend = render_extend_sv("uvs", "wave.usdb");
    assert(contains_line(uvs_extend, "$usdbDumpFinish;"));
    assert(!contains_line(uvs_extend, "$finish;"));

    return 0;
}
