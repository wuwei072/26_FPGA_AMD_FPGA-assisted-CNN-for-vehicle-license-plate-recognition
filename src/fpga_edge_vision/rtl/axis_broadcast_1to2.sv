`timescale 1ns / 1ps
// 同一份边缘数据，分别传给网格统计和边缘图DMA
module axis_broadcast_1to2 #(
    parameter integer DATA_WIDTH = 8
) 
(
    input aclk,
    input aresetn,

    input [DATA_WIDTH-1:0] s_axis_tdata,
    input s_axis_tvalid,
    output wire s_axis_tready,
    input s_axis_tlast,

    output wire [DATA_WIDTH-1:0] m0_axis_tdata,
    output reg  m0_axis_tvalid,
    input m0_axis_tready,
    output wire m0_axis_tlast,

    output wire [DATA_WIDTH-1:0] m1_axis_tdata,
    output reg  m1_axis_tvalid,
    input m1_axis_tready,
    output wire m1_axis_tlast
);

    // 两路共用这份缓存，valid分别记录哪一路还没收
    reg [DATA_WIDTH-1:0] data_reg;
    reg last_reg;

    assign m0_axis_tdata = data_reg;
    assign m1_axis_tdata = data_reg;
    assign m0_axis_tlast = last_reg;
    assign m1_axis_tlast = last_reg;

    // valid=0这一路已收完；两路都能收完，才允许换下一份数据
    assign s_axis_tready = (!m0_axis_tvalid || m0_axis_tready) &&(!m1_axis_tvalid || m1_axis_tready);

    always @(posedge aclk) begin
        if (!aresetn) begin
            data_reg <= {DATA_WIDTH{1'b0}};
            last_reg <= 1'b0;
            m0_axis_tvalid <= 1'b0;
            m1_axis_tvalid <= 1'b0;
        end
        else if (s_axis_tvalid && s_axis_tready) begin
            // 旧数据已收完，同一拍可以补进下一份
            data_reg <= s_axis_tdata;
            last_reg <= s_axis_tlast;
            m0_axis_tvalid <= 1'b1;
            m1_axis_tvalid <= 1'b1;
        end
        else begin
            // 收到的一路先清valid，没收到的一路继续等
            if (m0_axis_tvalid && m0_axis_tready)
                m0_axis_tvalid <= 1'b0;
            if (m1_axis_tvalid && m1_axis_tready)
                m1_axis_tvalid <= 1'b0;
        end
    end

endmodule
