# Place this file at <submission_root>/build/rebuild.tcl.
# The build entry loads board/board_files from this repository automatically.
set submission_root [file normalize [file join [file dirname [info script]] ..]]
set original_entry [file join $submission_root build vivado build_bd.tcl]
if {![file exists $original_entry]} {
    error "Missing build entry: $original_entry"
}
source $original_entry
