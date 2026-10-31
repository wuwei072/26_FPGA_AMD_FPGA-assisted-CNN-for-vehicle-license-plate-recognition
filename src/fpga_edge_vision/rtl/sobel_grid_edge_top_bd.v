// ============================================================================
// Vivado Module Reference wrapper：ROI输出 + 真实二值边缘图输出
// ============================================================================

`timescale 1ns / 1ps

module sobel_grid_edge_top_bd (
    (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 aclk CLK" *)
    (* X_INTERFACE_PARAMETER = "XIL_INTERFACENAME aclk, ASSOCIATED_BUSIF s_axis:m_axis:edge_m_axis, ASSOCIATED_RESET aresetn, FREQ_HZ 50000000" *)
    input  wire        aclk,

    (* X_INTERFACE_INFO = "xilinx.com:signal:reset:1.0 aresetn RST" *)
    (* X_INTERFACE_PARAMETER = "XIL_INTERFACENAME aresetn, POLARITY ACTIVE_LOW" *)
    input  wire        aresetn,

    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 s_axis TDATA" *)
    (* X_INTERFACE_PARAMETER = "XIL_INTERFACENAME s_axis, TDATA_NUM_BYTES 1, HAS_TKEEP 0, HAS_TLAST 1, HAS_TREADY 1, HAS_TSTRB 0, TDEST_WIDTH 0, TID_WIDTH 0, TUSER_WIDTH 0, LAYERED_METADATA undef" *)
    input  wire [7:0]  s_axis_tdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 s_axis TVALID" *)
    input  wire        s_axis_tvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 s_axis TREADY" *)
    output wire        s_axis_tready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 s_axis TLAST" *)
    input  wire        s_axis_tlast,

    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 m_axis TDATA" *)
    (* X_INTERFACE_PARAMETER = "XIL_INTERFACENAME m_axis, TDATA_NUM_BYTES 2, HAS_TKEEP 0, HAS_TLAST 1, HAS_TREADY 1, HAS_TSTRB 0, TDEST_WIDTH 0, TID_WIDTH 0, TUSER_WIDTH 0, LAYERED_METADATA undef" *)
    output wire [15:0] m_axis_tdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 m_axis TVALID" *)
    output wire        m_axis_tvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 m_axis TREADY" *)
    input  wire        m_axis_tready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 m_axis TLAST" *)
    output wire        m_axis_tlast,

    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 edge_m_axis TDATA" *)
    (* X_INTERFACE_PARAMETER = "XIL_INTERFACENAME edge_m_axis, TDATA_NUM_BYTES 1, HAS_TKEEP 0, HAS_TLAST 1, HAS_TREADY 1, HAS_TSTRB 0, TDEST_WIDTH 0, TID_WIDTH 0, TUSER_WIDTH 0, LAYERED_METADATA undef" *)
    output wire [7:0]  edge_m_axis_tdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 edge_m_axis TVALID" *)
    output wire        edge_m_axis_tvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 edge_m_axis TREADY" *)
    input  wire        edge_m_axis_tready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 edge_m_axis TLAST" *)
    output wire        edge_m_axis_tlast,

    input  wire [15:0] active_threshold
);

    sobel_grid_edge_top u_sobel_grid_edge_top (
        .aclk                   (aclk),
        .aresetn                (aresetn),

        .s_axis_tdata           (s_axis_tdata),
        .s_axis_tvalid          (s_axis_tvalid),
        .s_axis_tready          (s_axis_tready),
        .s_axis_tlast           (s_axis_tlast),

        .m_axis_tdata           (m_axis_tdata),
        .m_axis_tvalid          (m_axis_tvalid),
        .m_axis_tready          (m_axis_tready),
        .m_axis_tlast           (m_axis_tlast),

        .edge_m_axis_tdata      (edge_m_axis_tdata),
        .edge_m_axis_tvalid     (edge_m_axis_tvalid),
        .edge_m_axis_tready     (edge_m_axis_tready),
        .edge_m_axis_tlast      (edge_m_axis_tlast),

        .active_threshold       (active_threshold)
    );

endmodule

