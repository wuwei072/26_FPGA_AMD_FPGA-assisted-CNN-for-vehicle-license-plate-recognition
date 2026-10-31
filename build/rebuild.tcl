# Place this file at <submission_root>/build/rebuild.tcl.
# Configure/install the PYNQ-Z2 board repository before running it.
set submission_root [file normalize [file join [file dirname [info script]] ..]]
set original_entry [file join $submission_root src fpga_edge_vision hardware vivado sobel_edge_system build_bd.tcl]
if {![file exists $original_entry]} {
    error "Missing build entry: $original_entry"
}
source $original_entry
