# ============================================================================
# FPGA Edge Vision - PYNQ-Z2 ROI + real binary-edge return build
# Target: PYNQ-Z2 / xc7z020clg400-1
# Vivado: intended for 2025.1; uses only catalog IP and RTL module references.
#
# Run from the Vivado Tcl shell or in batch mode:
#   From the repository root: vivado -mode batch -source build/rebuild.tcl
#
# Generated artifacts:
#   build/work/sobel_edge_system/       Generated project and runs
#   board/deploy/sobel_edge.bit         PYNQ overlay bitstream
#   board/deploy/sobel_edge.hwh         Matching PYNQ hardware metadata
#   build/reports/current/             Address map, timing and utilization
# ============================================================================

namespace eval sobel_build {
    proc script_dir {} {
        return [file dirname [file normalize [info script]]]
    }

    proc require_one {objects description} {
        if {[llength $objects] != 1} {
            error "Expected exactly one $description, got [llength $objects]"
        }
        return [lindex $objects 0]
    }
}

set script_dir      [sobel_build::script_dir]
set submission_root [file normalize [file join $script_dir .. ..]]
set project_dir     [file join $submission_root build work sobel_edge_system]
set deploy_dir      [file join $submission_root board deploy]
set report_dir      [file join $submission_root build reports current]
set rtl_dir         [file join $submission_root src fpga_edge_vision rtl]
set xdc_file        [file join $script_dir sobel_edge_system.xdc]
set board_repo      [file join $submission_root board board_files]

set project_name sobel_edge_system
set design_name  sobel_edge_system
set part_name    xc7z020clg400-1

file mkdir $project_dir $deploy_dir $report_dir

# Load the board preset shipped with this repository before resolving its part.
# Keep other configured repositories available for the rest of this Vivado session.
if {![file isdirectory $board_repo]} {
    error "Missing repository board files: $board_repo"
}
set board_repos [get_param board.repoPaths]
if {[lsearch -exact $board_repos $board_repo] < 0} {
    lappend board_repos $board_repo
}
set_param board.repoPaths $board_repos

# The board preset supplies DDR and MIO parameters; do not silently use a bare part.
set board_matches [get_board_parts -quiet \
    -filter {BOARD_NAME =~ "*pynq-z2*"} -latest_file_version]
if {[llength $board_matches] == 0} {
    error "PYNQ-Z2 board part was not found after loading $board_repo. Check the bundled board.xml, preset.xml and part0_pins.xml."
}
set board_part [lindex $board_matches end]
puts "INFO: using board part $board_part"

create_project -force $project_name $project_dir -part $part_name
set_property board_part $board_part [current_project]
set_property target_language Verilog [current_project]
set_property simulator_language Mixed [current_project]

# Add the verified SystemVerilog RTL in dependency order.
set sv_rtl_files [list \
    [file join $rtl_dir sobel_axis.sv] \
    [file join $rtl_dir grid_counter.sv] \
    [file join $rtl_dir roi_engine.sv] \
    [file join $rtl_dir axis_broadcast_1to2.sv] \
    [file join $rtl_dir sobel_grid_edge_top.sv]]

foreach rtl_file $sv_rtl_files {
    if {![file exists $rtl_file]} {
        error "Missing RTL source: $rtl_file"
    }
}
add_files -norecurse $sv_rtl_files
set_property file_type SystemVerilog [get_files $sv_rtl_files]

# Vivado Block Design Module Reference 不接受 SystemVerilog 作为引用顶层。
# 使用普通 Verilog wrapper 暴露 AXI4-Stream 接口，内部逻辑仍为上述已验证 RTL。
set bd_wrapper_file [file join $rtl_dir sobel_grid_edge_top_bd.v]
if {![file exists $bd_wrapper_file]} {
    error "Missing Block Design RTL wrapper: $bd_wrapper_file"
}
add_files -norecurse $bd_wrapper_file
set_property file_type Verilog [get_files $bd_wrapper_file]
update_compile_order -fileset sources_1

if {![file exists $xdc_file]} {
    error "Missing constraint file: $xdc_file"
}
add_files -fileset constrs_1 -norecurse $xdc_file
set_property PROCESSING_ORDER LATE [get_files $xdc_file]

create_bd_design $design_name

# --------------------------------------------------------------------------
# IP instances
# --------------------------------------------------------------------------
set ps7 [create_bd_cell -type ip \
    -vlnv xilinx.com:ip:processing_system7:5.5 processing_system7_0]

# The official PYNQ-Z2 board preset supplies the board-specific DDR and MIO
# configuration, including UART and SD-card routing.
apply_bd_automation -rule xilinx.com:bd_rule:processing_system7 \
    -config {apply_board_preset "1" make_external "FIXED_IO, DDR" Master "Disable" Slave "Disable"} \
    $ps7

# Conservative 50 MHz build: use one shared PL/AXI clock domain.
set_property -dict [list \
    CONFIG.PCW_USE_M_AXI_GP0 {1} \
    CONFIG.PCW_M_AXI_GP0_FREQMHZ {50.000000} \
    CONFIG.PCW_USE_S_AXI_HP0 {1} \
    CONFIG.PCW_S_AXI_HP0_DATA_WIDTH {64} \
    CONFIG.PCW_EN_CLK0_PORT {1} \
    CONFIG.PCW_FPGA_FCLK0_ENABLE {1} \
    CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ {50.000000}] $ps7

set dma [create_bd_cell -type ip \
    -vlnv xilinx.com:ip:axi_dma:7.1 axi_dma_0]
set_property -dict [list \
    CONFIG.c_include_sg {0} \
    CONFIG.c_micro_dma {0} \
    CONFIG.c_include_mm2s {1} \
    CONFIG.c_include_s2mm {1} \
    CONFIG.c_m_axi_mm2s_data_width {64} \
    CONFIG.c_m_axis_mm2s_tdata_width {8} \
    CONFIG.c_include_mm2s_dre {1} \
    CONFIG.c_mm2s_burst_size {16} \
    CONFIG.c_m_axi_s2mm_data_width {64} \
    CONFIG.c_s_axis_s2mm_tdata_width {16} \
    CONFIG.c_include_s2mm_dre {1} \
    CONFIG.c_s2mm_burst_size {16} \
    CONFIG.c_sg_length_width {26} \
    CONFIG.c_addr_width {32}] $dma

# 第二路DMA只接收307200字节0/255二值Sobel边缘图。
set dma_edge [create_bd_cell -type ip \
    -vlnv xilinx.com:ip:axi_dma:7.1 axi_dma_edge]
set_property -dict [list \
    CONFIG.c_include_sg {0} \
    CONFIG.c_micro_dma {0} \
    CONFIG.c_include_mm2s {0} \
    CONFIG.c_include_s2mm {1} \
    CONFIG.c_m_axi_s2mm_data_width {64} \
    CONFIG.c_s_axis_s2mm_tdata_width {8} \
    CONFIG.c_include_s2mm_dre {1} \
    CONFIG.c_s2mm_burst_size {16} \
    CONFIG.c_sg_length_width {26} \
    CONFIG.c_addr_width {32}] $dma_edge

# Control path: PS M_AXI_GP0 -> both DMA S_AXI_LITE interfaces.
set ctrl_ic [create_bd_cell -type ip \
    -vlnv xilinx.com:ip:axi_interconnect:2.1 axi_interconnect_ctrl]
set_property -dict [list CONFIG.NUM_SI {1} CONFIG.NUM_MI {2}] $ctrl_ic

# DDR data path: main DMA MM2S/S2MM and edge DMA S2MM -> PS S_AXI_HP0.
set mem_ic [create_bd_cell -type ip \
    -vlnv xilinx.com:ip:axi_interconnect:2.1 axi_interconnect_mem]
set_property -dict [list CONFIG.NUM_SI {3} CONFIG.NUM_MI {1}] $mem_ic

set rst [create_bd_cell -type ip \
    -vlnv xilinx.com:ip:proc_sys_reset:5.0 rst_ps7_0_50m]
# 两个复位输入均低有效；未使用的aux_reset_in必须接1，不能接0。
set_property -dict [list CONFIG.C_EXT_RESET_HIGH {0} \
    CONFIG.C_AUX_RESET_HIGH {0}] $rst

set const_zero [create_bd_cell -type ip \
    -vlnv xilinx.com:ip:xlconstant:1.1 const_zero]
set_property -dict [list CONFIG.CONST_WIDTH {1} CONFIG.CONST_VAL {0}] $const_zero

set const_one [create_bd_cell -type ip \
    -vlnv xilinx.com:ip:xlconstant:1.1 const_one]
set_property -dict [list CONFIG.CONST_WIDTH {1} CONFIG.CONST_VAL {1}] $const_one

set active_threshold_768 [create_bd_cell -type ip \
    -vlnv xilinx.com:ip:xlconstant:1.1 active_threshold_768]
set_property -dict [list \
    CONFIG.CONST_WIDTH {16} \
    CONFIG.CONST_VAL {768}] $active_threshold_768

# Verilog Module Reference wrapper contains the verified SystemVerilog top.
set sobel [create_bd_cell -type module \
    -reference sobel_grid_edge_top_bd sobel_grid_edge_top_0]

# Verify that Vivado inferred both AXI4-Stream interfaces from the RTL names.
sobel_build::require_one \
    [get_bd_intf_pins -quiet sobel_grid_edge_top_0/s_axis] \
    "sobel_grid_edge_top_0/s_axis interface"
sobel_build::require_one \
    [get_bd_intf_pins -quiet sobel_grid_edge_top_0/m_axis] \
    "sobel_grid_edge_top_0/m_axis interface"
sobel_build::require_one \
    [get_bd_intf_pins -quiet sobel_grid_edge_top_0/edge_m_axis] \
    "sobel_grid_edge_top_0/edge_m_axis interface"

# --------------------------------------------------------------------------
# AXI4-Stream datapath.  The interface connections include TVALID, TREADY,
# TDATA and TLAST; TLAST must reach S_AXIS_S2MM to terminate the DMA receive.
# --------------------------------------------------------------------------
connect_bd_intf_net \
    [get_bd_intf_pins axi_dma_0/M_AXIS_MM2S] \
    [get_bd_intf_pins sobel_grid_edge_top_0/s_axis]

connect_bd_intf_net \
    [get_bd_intf_pins sobel_grid_edge_top_0/m_axis] \
    [get_bd_intf_pins axi_dma_0/S_AXIS_S2MM]

connect_bd_intf_net \
    [get_bd_intf_pins sobel_grid_edge_top_0/edge_m_axis] \
    [get_bd_intf_pins axi_dma_edge/S_AXIS_S2MM]

# AXI-Lite DMA control path.
connect_bd_intf_net \
    [get_bd_intf_pins processing_system7_0/M_AXI_GP0] \
    [get_bd_intf_pins axi_interconnect_ctrl/S00_AXI]
connect_bd_intf_net \
    [get_bd_intf_pins axi_interconnect_ctrl/M00_AXI] \
    [get_bd_intf_pins axi_dma_0/S_AXI_LITE]
connect_bd_intf_net \
    [get_bd_intf_pins axi_interconnect_ctrl/M01_AXI] \
    [get_bd_intf_pins axi_dma_edge/S_AXI_LITE]

# DMA memory-mapped paths to DDR through HP0.
connect_bd_intf_net \
    [get_bd_intf_pins axi_dma_0/M_AXI_MM2S] \
    [get_bd_intf_pins axi_interconnect_mem/S00_AXI]
connect_bd_intf_net \
    [get_bd_intf_pins axi_dma_0/M_AXI_S2MM] \
    [get_bd_intf_pins axi_interconnect_mem/S01_AXI]
connect_bd_intf_net \
    [get_bd_intf_pins axi_dma_edge/M_AXI_S2MM] \
    [get_bd_intf_pins axi_interconnect_mem/S02_AXI]
connect_bd_intf_net \
    [get_bd_intf_pins axi_interconnect_mem/M00_AXI] \
    [get_bd_intf_pins processing_system7_0/S_AXI_HP0]

# --------------------------------------------------------------------------
# One 50 MHz clock domain for PS AXI, both DMAs, interconnects and custom RTL.
# --------------------------------------------------------------------------
connect_bd_net [get_bd_pins processing_system7_0/FCLK_CLK0] \
    [get_bd_pins processing_system7_0/M_AXI_GP0_ACLK] \
    [get_bd_pins processing_system7_0/S_AXI_HP0_ACLK] \
    [get_bd_pins axi_dma_0/s_axi_lite_aclk] \
    [get_bd_pins axi_dma_0/m_axi_mm2s_aclk] \
    [get_bd_pins axi_dma_0/m_axi_s2mm_aclk] \
    [get_bd_pins axi_dma_edge/s_axi_lite_aclk] \
    [get_bd_pins axi_dma_edge/m_axi_s2mm_aclk] \
    [get_bd_pins axi_interconnect_ctrl/ACLK] \
    [get_bd_pins axi_interconnect_ctrl/S00_ACLK] \
    [get_bd_pins axi_interconnect_ctrl/M00_ACLK] \
    [get_bd_pins axi_interconnect_ctrl/M01_ACLK] \
    [get_bd_pins axi_interconnect_mem/ACLK] \
    [get_bd_pins axi_interconnect_mem/S00_ACLK] \
    [get_bd_pins axi_interconnect_mem/S01_ACLK] \
    [get_bd_pins axi_interconnect_mem/S02_ACLK] \
    [get_bd_pins axi_interconnect_mem/M00_ACLK] \
    [get_bd_pins rst_ps7_0_50m/slowest_sync_clk] \
    [get_bd_pins sobel_grid_edge_top_0/aclk]

# Reset controller inputs. The active-low polarity propagates automatically
# from FCLK_RESET0_N to the reset controller in Vivado 2025.1.
connect_bd_net [get_bd_pins processing_system7_0/FCLK_RESET0_N] \
    [get_bd_pins rst_ps7_0_50m/ext_reset_in]
connect_bd_net [get_bd_pins const_zero/dout] \
    [get_bd_pins rst_ps7_0_50m/mb_debug_sys_rst]
connect_bd_net [get_bd_pins const_one/dout] \
    [get_bd_pins rst_ps7_0_50m/aux_reset_in] \
    [get_bd_pins rst_ps7_0_50m/dcm_locked]

# Interconnect reset and peripheral reset are both synchronous to FCLK_CLK0.
connect_bd_net [get_bd_pins rst_ps7_0_50m/interconnect_aresetn] \
    [get_bd_pins axi_interconnect_ctrl/ARESETN] \
    [get_bd_pins axi_interconnect_ctrl/S00_ARESETN] \
    [get_bd_pins axi_interconnect_ctrl/M00_ARESETN] \
    [get_bd_pins axi_interconnect_ctrl/M01_ARESETN] \
    [get_bd_pins axi_interconnect_mem/ARESETN] \
    [get_bd_pins axi_interconnect_mem/S00_ARESETN] \
    [get_bd_pins axi_interconnect_mem/S01_ARESETN] \
    [get_bd_pins axi_interconnect_mem/S02_ARESETN] \
    [get_bd_pins axi_interconnect_mem/M00_ARESETN]

connect_bd_net [get_bd_pins rst_ps7_0_50m/peripheral_aresetn] \
    [get_bd_pins axi_dma_0/axi_resetn] \
    [get_bd_pins axi_dma_edge/axi_resetn] \
    [get_bd_pins sobel_grid_edge_top_0/aresetn]

# Sobel threshold is fixed at 80 in RTL; only the active-grid threshold is wired here.
connect_bd_net [get_bd_pins active_threshold_768/dout] \
    [get_bd_pins sobel_grid_edge_top_0/active_threshold]

# Allocate all reachable address segments, then force a stable DMA register
# address for Python/PYNQ software.
assign_bd_address
set dma_reg_seg [sobel_build::require_one \
    [get_bd_addr_segs -quiet axi_dma_0/S_AXI_LITE/Reg] \
    "AXI DMA register segment"]
set ps_data_space [sobel_build::require_one \
    [get_bd_addr_spaces -quiet processing_system7_0/Data] \
    "PS data address space"]
assign_bd_address -offset 0x40400000 -range 0x00010000 \
    -target_address_space $ps_data_space $dma_reg_seg -force

set edge_dma_reg_seg [sobel_build::require_one \
    [get_bd_addr_segs -quiet axi_dma_edge/S_AXI_LITE/Reg] \
    "edge AXI DMA register segment"]
assign_bd_address -offset 0x40410000 -range 0x00010000 \
    -target_address_space $ps_data_space $edge_dma_reg_seg -force

regenerate_bd_layout
validate_bd_design

# Fail early if clock propagation did not produce the requested 50 MHz FCLK.
set actual_fclk0_hz [get_property CONFIG.FREQ_HZ \
    [get_bd_pins processing_system7_0/FCLK_CLK0]]
if {$actual_fclk0_hz != 50000000} {
    error "FCLK_CLK0 frequency mismatch: expected 50000000 Hz, got $actual_fclk0_hz Hz"
}
puts "INFO: verified FCLK_CLK0 = $actual_fclk0_hz Hz"

# 配置传播后仍须满足低有效辅助复位的约定，避免再次永久复位。
if {[get_property CONFIG.C_AUX_RESET_HIGH $rst] != 0} {
    error "aux_reset_in polarity changed: expected ACTIVE_LOW tied to const_one"
}
save_bd_design

set bd_file [sobel_build::require_one \
    [get_files -quiet ${design_name}.bd] \
    "$design_name block-design file"]

generate_target all $bd_file
set wrapper_files [make_wrapper -files $bd_file -top]
add_files -norecurse $wrapper_files
set_property top ${design_name}_wrapper [get_filesets sources_1]
update_compile_order -fileset sources_1

# Keep a machine-generated address report alongside the human-readable table.
# Some Vivado 2025.1 installations provide neither report_bd_address nor the
# redirect helper, so use only standard Tcl file I/O and Vivado get_property.
set address_report_path [file join $report_dir address_map_vivado.txt]
set address_report_file [open $address_report_path w]
puts $address_report_file "FPGA Edge Vision - Vivado BD address map"
puts $address_report_file ""

foreach address_space [lsort [get_bd_addr_spaces]] {
    puts $address_report_file "ADDRESS_SPACE $address_space"
}

foreach address_segment [lsort [get_bd_addr_segs]] {
    puts $address_report_file ""
    puts $address_report_file "ADDRESS_SEGMENT $address_segment"
    foreach property_name {OFFSET RANGE USAGE} {
        if {![catch {get_property $property_name $address_segment} property_value]} {
            puts $address_report_file "  $property_name=$property_value"
        }
    }
}
close $address_report_file

# --------------------------------------------------------------------------
# Synthesis, implementation, bitstream and PYNQ artifact export.
# --------------------------------------------------------------------------
launch_runs synth_1 -jobs 4
wait_on_run synth_1
set synth_status [get_property STATUS [get_runs synth_1]]
if {![string match *Complete* $synth_status]} {
    error "Synthesis failed: $synth_status"
}

launch_runs impl_1 -to_step write_bitstream -jobs 4
wait_on_run impl_1
set impl_status [get_property STATUS [get_runs impl_1]]
if {![string match *Complete* $impl_status]} {
    error "Implementation/bitstream failed: $impl_status"
}

set bit_candidates [glob -nocomplain \
    [file join $project_dir ${project_name}.runs impl_1 *.bit]]
set bit_file [sobel_build::require_one $bit_candidates "implemented bitstream"]

set hwh_candidates [lsort -unique [concat \
    [glob -nocomplain [file join $project_dir ${project_name}.gen sources_1 bd $design_name hw_handoff *.hwh]] \
    [glob -nocomplain [file join $project_dir ${project_name}.srcs sources_1 bd $design_name hw_handoff *.hwh]]]]
set hwh_file [sobel_build::require_one $hwh_candidates "block-design HWH file"]
# Refresh reports from the same implemented design as the exported overlay.
open_run impl_1
report_timing_summary -delay_type min_max -report_unconstrained \
    -check_timing_verbose -file [file join $report_dir timing_summary.rpt]
report_utilization -file [file join $report_dir utilization.rpt]

# Resolve both members before replacing the deployment pair.  Both come from this run.
file copy -force $bit_file [file join $deploy_dir sobel_edge.bit]
file copy -force $hwh_file [file join $deploy_dir sobel_edge.hwh]

puts "INFO: build complete"
puts "INFO: bitstream: [file join $deploy_dir sobel_edge.bit]"
puts "INFO: metadata:  [file join $deploy_dir sobel_edge.hwh]"
puts "INFO: reports:   $report_dir"
puts "INFO: Check and refresh board/deploy/UPLOAD_MANIFEST.json before uploading the rebuilt overlay."
puts "INFO: Hardware validation is still required on the board."

