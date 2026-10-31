# Vivado 2025.1 RTL behavioral simulation helper.
# Source this file in a NEW Vivado window, then call rtl_sim_init.
# Does not alter RTL, testbenches, Golden files, or the main Vivado project.
namespace eval rtl_check {
    variable default_root [file normalize [file join [file dirname [info script]] ..]]
    variable root ""
    variable workspace ""
    variable evidence ""
    variable project_name "rtl_verify"
}

proc rtl_sim_init {{root ""} {output_root ""}} {
    if {[llength [get_projects -quiet]] != 0} {
        error "Use a new Vivado window with no project open; the helper will not close your existing project."
    }
    if {$root eq ""} {set root $rtl_check::default_root}
    set root [file normalize $root]
    if {[regexp {\s} $root]} {error "Use a repository path without spaces for XSim plusargs."}
    set hw [file join $root src fpga_edge_vision hardware]
    set rtl_names {sobel_axis.sv grid_counter.sv roi_engine.sv axis_broadcast_1to2.sv sobel_grid_edge_top.sv}
    set tb_names {tb_sobel_axis.sv tb_grid_counter.sv tb_roi_engine.sv tb_sobel_grid_edge_top.sv}
    set rtl_files {}; set tb_files {}
    foreach name $rtl_names {
        set f [file join $hw rtl $name]
        if {![file isfile $f]} {error "Missing RTL: $f"}
        lappend rtl_files $f
    }
    foreach name $tb_names {
        set f [file join $hw sim $name]
        if {![file isfile $f]} {error "Missing testbench: $f"}
        lappend tb_files $f
    }
    if {$output_root eq ""} {set output_root [file join $root sim]}
    set output_root [file normalize $output_root]
    set stamp "[clock format [clock seconds] -format %Y%m%d_%H%M%S]_[clock clicks -milliseconds]"
    set rtl_check::root $root
    set rtl_check::workspace [file join $output_root work rtl_$stamp]
    set rtl_check::evidence [file join $output_root logs rtl_$stamp]
    file mkdir $rtl_check::evidence
    create_project $rtl_check::project_name $rtl_check::workspace -part xc7z020clg400-1
    set_property target_simulator XSim [current_project]
    set_property target_language Verilog [current_project]
    set_property simulator_language Mixed [current_project]
    add_files -fileset sources_1 -norecurse $rtl_files
    add_files -fileset sim_1 -norecurse $tb_files
    set_property file_type SystemVerilog [get_files -all *.sv]
    set_property top sobel_grid_edge_top [get_filesets sources_1]
    set_property top_lib xil_defaultlib [get_filesets sim_1]
    set_property top tb_sobel_axis [get_filesets sim_1]
    set_property xsim.simulate.runtime 0ns [get_filesets sim_1]
    update_compile_order -fileset sources_1
    update_compile_order -fileset sim_1
    set f [open [file join $rtl_check::evidence source_files.txt] w]
    puts $f "Repository: $root"
    puts $f "Vivado: [version -short]"
    puts $f "Part: xc7z020clg400-1"
    foreach p [concat $rtl_files $tb_files] {
        puts $f "$p | bytes=[file size $p] | mtime=[file mtime $p]"
    }
    close $f
    puts "READY: rtl_sim sobel | rtl_sim grid | rtl_sim roi | rtl_sim top single_target"
    puts "Evidence: $rtl_check::evidence"
}

proc rtl_check_archive {destination} {
    set rundir [file join $rtl_check::workspace ${rtl_check::project_name}.sim sim_1 behav xsim]
    foreach name {compile.log elaborate.log simulate.log} {
        set p [file join $rundir $name]
        if {[file isfile $p]} {file copy $p [file join $destination $name]}
    }
    return [file join $destination simulate.log]
}

proc rtl_sim {kind {case single_target}} {
    if {$rtl_check::root eq "" || [llength [get_projects -quiet]] != 1} {
        error "First run rtl_sim_init in a new Vivado window."
    }
    if {[file normalize [get_property DIRECTORY [current_project]]] ne $rtl_check::workspace} {
        error "The current project is not this helper's simulation project."
    }
    if {$case ni {single_target multi_target noise_target}} {error "Unknown vector case: $case"}
    if {$kind ni {sobel grid roi top}} {error "Use sobel, grid, roi, or top."}
    if {$kind eq "roi" && $case ne "single_target"} {
        error "ROI testbench has fixed single-target expectations plus an internal tie test. Use rtl_sim roi."
    }
    set vec [file join $rtl_check::root src fpga_edge_vision hardware sim vectors]
    set stem "${case}_640x480"
    set input [file join $vec ${stem}_input.bin]
    set edge [file join $vec ${stem}_expected.bin]
    set counts [file join $vec ${stem}_grid_counts.hex]
    switch -- $case {
        single_target {set expected 160,160,160,160,4,9167}
        multi_target {set expected 80,80,240,160,6,8750}
        noise_target {set expected 400,160,160,160,4,9167}
    }
    switch -- $kind {
        sobel {set top tb_sobel_axis; set needed [list $input $edge]; set pairs [list IN $input EXP $edge]}
        grid {set top tb_grid_counter; set needed [list $edge $counts]; set pairs [list EDGE $edge COUNTS $counts]}
        roi {set top tb_roi_engine; set needed [list $counts]; set pairs [list COUNTS $counts]}
        top {set top tb_sobel_grid_edge_top; set needed [list $input $edge]; set pairs [list IN $input EDGE $edge EXPECTED $expected]}
    }
    foreach p $needed {
        if {![file isfile $p]} {error "Missing vector: $p"}
        if {[file extension $p] eq ".bin" && [file size $p] != 307200} {error "Wrong vector length: $p"}
    }
    # Only this helper's separate simulation project is active here.
    catch {close_sim}
    set options [list -onfinish stop]
    foreach {name value} $pairs {lappend options -testplusarg "${name}=${value}"}
    set_property top $top [get_filesets sim_1]
    set_property -name xsim.simulate.xsim.more_options -value [join $options " "] -objects [get_filesets sim_1]
    set_property xsim.simulate.runtime 0ns [get_filesets sim_1]
    update_compile_order -fileset sim_1
    set tag "${kind}_${case}_[clock clicks -milliseconds]"
    set destination [file join $rtl_check::evidence $tag]
    file mkdir $destination
    set f [open [file join $destination case_info.txt] w]
    puts $f "Top: $top"
    puts $f "Vector: $case"
    puts $f "Options: [join $options { }]"
    puts $f "Started: [clock format [clock seconds] -format {%Y-%m-%d %H:%M:%S}]"
    close $f
    if {[catch {
        launch_simulation -simset sim_1 -mode behavioral
        run all
    } message settings]} {
        rtl_check_archive $destination
        return -options $settings $message
    }
    set log [rtl_check_archive $destination]
    if {![file isfile $log]} {error "Simulation finished but no simulate.log found. Inspect XSim output."}
    set f [open $log r]; set transcript [read $f]; close $f
    set pass [regexp {(^|\n)(PASS|grid counts: 48, mismatches: 0, PASS)\r?(\n|$)} $transcript]
    if {!$pass || [regexp {(^|\n)(FAIL:|ERROR:)} $transcript]} {
        error "No clean PASS recorded. Inspect: $log"
    }
    puts "RTL PASS: $kind / $case"
    puts "Evidence saved: $destination"
    puts "Waveform remains open; the next rtl_sim call closes this simulation."
    return $destination
}

puts "Loaded RTL helper. In a new Vivado window: rtl_sim_init"
puts "Then: rtl_sim sobel; rtl_sim grid; rtl_sim roi; rtl_sim top single_target"
