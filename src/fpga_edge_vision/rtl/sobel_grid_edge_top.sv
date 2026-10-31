`timescale 1ns / 1ps
// 双DMA版本：一路回ROI，另一路回真实Sobel边缘图
module sobel_grid_edge_top (
    input aclk,
    input aresetn,

    input [7:0] s_axis_tdata,
    input s_axis_tvalid,
    output wire s_axis_tready,
    input s_axis_tlast,

    // x、y、宽、高、网格数、缩减率
    output wire [15:0] m_axis_tdata,
    output wire m_axis_tvalid,
    input m_axis_tready,
    output wire m_axis_tlast,

    // 一帧640x480，每个边缘像素仍占8位
    output wire [7:0] edge_m_axis_tdata,
    output wire edge_m_axis_tvalid,
    input edge_m_axis_tready,
    output wire edge_m_axis_tlast,

    input [15:0] active_threshold
);

    // Sobel到广播器
    wire [7:0] sobel_edge_tdata;
    wire sobel_edge_tvalid;
    wire sobel_edge_tready;
    wire sobel_edge_tlast;

    // 广播器m0送网格统计，m1直接接边缘图输出
    wire [7:0] grid_edge_tdata;
    wire grid_edge_tvalid;
    wire grid_edge_tready;
    wire grid_edge_tlast;

    // 48个计数送ROI模块
    wire [15:0] count_tdata;
    wire count_tvalid;
    wire count_tready;
    wire count_tlast;

    sobel_axis u_sobel_axis (
        .aclk(aclk),
        .aresetn(aresetn),

        .s_axis_tdata(s_axis_tdata),
        .s_axis_tvalid(s_axis_tvalid),
        .s_axis_tready(s_axis_tready),
        .s_axis_tlast(s_axis_tlast),

        .m_axis_tdata(sobel_edge_tdata),
        .m_axis_tvalid(sobel_edge_tvalid),
        .m_axis_tready(sobel_edge_tready),
        .m_axis_tlast(sobel_edge_tlast)
    );

    axis_broadcast_1to2 #(
        .DATA_WIDTH(8)
    ) u_edge_broadcast (
        .aclk(aclk),
        .aresetn(aresetn),

        .s_axis_tdata(sobel_edge_tdata),
        .s_axis_tvalid(sobel_edge_tvalid),
        .s_axis_tready(sobel_edge_tready),
        .s_axis_tlast(sobel_edge_tlast),

        .m0_axis_tdata(grid_edge_tdata),
        .m0_axis_tvalid(grid_edge_tvalid),
        .m0_axis_tready(grid_edge_tready),
        .m0_axis_tlast(grid_edge_tlast),

        .m1_axis_tdata(edge_m_axis_tdata),
        .m1_axis_tvalid(edge_m_axis_tvalid),
        .m1_axis_tready(edge_m_axis_tready),
        .m1_axis_tlast(edge_m_axis_tlast)
    );

    grid_counter u_grid_counter (
        .aclk(aclk),
        .aresetn(aresetn),

        .s_axis_tdata(grid_edge_tdata),
        .s_axis_tvalid(grid_edge_tvalid),
        .s_axis_tready(grid_edge_tready),
        .s_axis_tlast(grid_edge_tlast),

        .m_axis_tdata(count_tdata),
        .m_axis_tvalid(count_tvalid),
        .m_axis_tready(count_tready),
        .m_axis_tlast(count_tlast),

        .threshold(16'd80),
        .enable(1'b1)
    );

    roi_engine u_roi_engine (
        .aclk(aclk),
        .aresetn(aresetn),

        .s_axis_tdata(count_tdata),
        .s_axis_tvalid(count_tvalid),
        .s_axis_tready(count_tready),
        .s_axis_tlast(count_tlast),

        .m_axis_tdata(m_axis_tdata),
        .m_axis_tvalid(m_axis_tvalid),
        .m_axis_tready(m_axis_tready),
        .m_axis_tlast(m_axis_tlast),

        .active_threshold(active_threshold)
    );

endmodule

