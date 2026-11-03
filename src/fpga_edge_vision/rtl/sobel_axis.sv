// 640x480 灰度输入，输出阈值为80的二值Sobel边缘图
// 图像四周输出0，行末和帧末在内部补零，补零不占输入数据
`timescale 1ns / 1ps
module sobel_axis (
    input        aclk,
    input        aresetn,

    input  [7:0] s_axis_tdata,
    input        s_axis_tvalid,
    output wire       s_axis_tready,
    input        s_axis_tlast,

    output wire [7:0] m_axis_tdata,
    output wire       m_axis_tvalid,
    input        m_axis_tready,
    output wire       m_axis_tlast
);

    localparam integer WIDTH  = 640;
    localparam integer HEIGHT = 480;
    localparam [7:0] EDGE_THRESHOLD = 8'd80;

    localparam [1:0] ST_INPUT      = 2'd0,
                     ST_PAD_COLUMN = 2'd1,
                     ST_PAD_ROW    = 2'd2;

    reg [1:0] state;

    // 每帧开始时，缓存的旧内容只会落在边界，最后会被置0
    (* ram_style = "block" *) reg [7:0] line_buf0 [0:WIDTH-1];
    (* ram_style = "block" *) reg [7:0] line_buf1 [0:WIDTH-1];

    reg [7:0] line0_q;
    reg [7:0] line1_q;

    // 本拍送给行缓存的像素和坐标
    reg       issue_valid;
    reg       issue_mem_read;
    reg       issue_mem_write;
    reg [9:0] issue_x;
    reg [9:0] issue_y;
    reg [7:0] issue_current;

    // RAM同步读等一拍，坐标、当前像素和使能一起延迟
    reg       read_valid;
    reg       read_mem_valid;
    reg       read_mem_write;
    reg [9:0] read_x;
    reg [9:0] read_y;
    reg [7:0] read_current;

    reg [9:0] input_x;
    reg [9:0] input_y;
    reg [9:0] pad_x;

    // 三行各保留前两列，再加新读出的这一列，组成3x3窗口
    reg [7:0] w01, w02;
    reg [7:0] w11, w12;
    reg [7:0] w21, w22;

    wire [7:0] step_upper, step_middle;

    // 四级流水：窗口 -> Gx/Gy -> 幅值和 -> 二值化
    // 坐标跟着像素传递，用于最后一级判断边界
    reg       stage1_valid;
    reg       stage1_last;
    reg [9:0] stage1_x;
    reg [9:0] stage1_y;
    reg [7:0] stage1_p00, stage1_p01, stage1_p02;
    reg [7:0] stage1_p10, stage1_p12; 
    reg [7:0] stage1_p20, stage1_p21, stage1_p22;

    reg       stage2_valid;
    reg       stage2_last;
    reg [9:0] stage2_x;
    reg [9:0] stage2_y;
    reg signed [12:0] stage2_gx;
    reg signed [12:0] stage2_gy;

    reg       stage3_valid;
    reg       stage3_last;
    reg [9:0] stage3_x;
    reg [9:0] stage3_y;
    reg [13:0] stage3_sum;

    reg       stage4_valid;
    reg       stage4_last;
    reg [7:0] stage4_data;

    reg [12:0] left_sum, right_sum;
    reg [12:0] top_sum, bottom_sum;
    reg signed [12:0] gx_next;
    reg signed [12:0] gy_next;
    reg [12:0] abs_gx_next;
    reg [12:0] abs_gy_next;
    reg [13:0] sum_next;
    reg [7:0] mag_sat_next;
    reg       stage3_interior;

    wire pipeline_advance;
    wire input_fire;

    // 输出级为空或本拍成功握手时，所有级一起前进一拍
    assign pipeline_advance = !stage4_valid || m_axis_tready;
    assign s_axis_tready = aresetn && (state == ST_INPUT) && pipeline_advance;
    assign input_fire = s_axis_tvalid && s_axis_tready;

    assign m_axis_tdata  = stage4_data;
    assign m_axis_tvalid = aresetn && stage4_valid;
    assign m_axis_tlast  = m_axis_tvalid && stage4_last;

    // 真实输入像素由 AXI 握手触发，虚拟右列和末行由状态机产生
    always @* begin
        issue_valid     = 1'b0;
        issue_mem_read  = 1'b0;
        issue_mem_write = 1'b0;
        issue_x         = 10'd0;
        issue_y         = 10'd0;
        issue_current   = 8'd0;

        case (state)
            ST_INPUT: begin
                if (input_fire) begin
                    issue_valid     = 1'b1;
                    issue_mem_read  = 1'b1;
                    issue_mem_write = 1'b1;
                    issue_x         = input_x;
                    issue_y         = input_y;
                    issue_current   = s_axis_tdata;
                end
            end

            ST_PAD_COLUMN: begin
                issue_valid = 1'b1;
                issue_x     = WIDTH;
                issue_y     = input_y;
            end

            default: begin // ST_PAD_ROW
                issue_valid = 1'b1;
                issue_x     = pad_x;
                issue_y     = HEIGHT;
                if (pad_x < WIDTH)
                    issue_mem_read = 1'b1;
            end
        endcase
    end

    always @(posedge aclk) begin
        if (aresetn && pipeline_advance) begin
            if (issue_mem_read)
                line0_q <= line_buf0[issue_x];

            if (read_valid && read_mem_write)
                line_buf0[read_x] <= line1_q;
        end
    end

    always @(posedge aclk) begin
        if (aresetn && pipeline_advance) begin
            if (issue_mem_read)
                line1_q <= line_buf1[issue_x];

            if (read_valid && read_mem_write)
                line_buf1[read_x] <= read_current;
        end
    end

    // 补右侧一列时没有RAM读取，这两行直接补0
    assign step_upper  = read_mem_valid ? line0_q : 8'd0;
    assign step_middle = read_mem_valid ? line1_q : 8'd0;

    always @* begin
        left_sum = stage1_p00 + 2 * stage1_p10 + stage1_p20;
        right_sum = stage1_p02 + 2 * stage1_p12 + stage1_p22;

        top_sum = stage1_p00 + 2 * stage1_p01 + stage1_p02;
        bottom_sum = stage1_p20 + 2 * stage1_p21 + stage1_p22;

        // 右列减左列、下行减上行，signed保留负梯度
        gx_next = right_sum - left_sum;
        gy_next = bottom_sum - top_sum;
    end

    //求|Gx|+|Gy|近似梯度
    always @* begin
        abs_gx_next = stage2_gx[12] ? (13'd0 - stage2_gx) : stage2_gx;
        abs_gy_next = stage2_gy[12] ? (13'd0 - stage2_gy) : stage2_gy;
        sum_next = {1'b0, abs_gx_next} + {1'b0, abs_gy_next};
    end

    // 幅值限制255；边界判断用流水线中坐标
    always @* begin
        mag_sat_next = (stage3_sum > 14'd255) ? 8'd255 : stage3_sum[7:0];
        stage3_interior = (stage3_x >= 1) && (stage3_x <= WIDTH - 2) && (stage3_y >= 1) && (stage3_y <= HEIGHT - 2);
    end

    // 所有流水级一起暂停
    always @(posedge aclk) begin
        if (!aresetn) begin
            state        <= ST_INPUT;
            input_x      <= 10'd0;
            input_y      <= 10'd0;
            pad_x        <= 10'd0;

            read_valid     <= 1'b0;
            read_mem_valid <= 1'b0;
            read_mem_write <= 1'b0;
            read_x         <= 10'd0;
            read_y         <= 10'd0;
            read_current   <= 8'd0;

            w01 <= 8'd0; w02 <= 8'd0;
            w11 <= 8'd0; w12 <= 8'd0;
            w21 <= 8'd0; w22 <= 8'd0;

            stage1_valid <= 1'b0;
            stage1_last  <= 1'b0;
            stage1_x     <= 10'd0;
            stage1_y     <= 10'd0;
            stage1_p00 <= 8'd0; stage1_p01 <= 8'd0; stage1_p02 <= 8'd0;
            stage1_p10 <= 8'd0; stage1_p12 <= 8'd0;
            stage1_p20 <= 8'd0; stage1_p21 <= 8'd0; stage1_p22 <= 8'd0;

            stage2_valid <= 1'b0;
            stage2_last  <= 1'b0;
            stage2_x     <= 10'd0;
            stage2_y     <= 10'd0;
            stage2_gx    <= 13'sd0;
            stage2_gy    <= 13'sd0;

            stage3_valid <= 1'b0;
            stage3_last  <= 1'b0;
            stage3_x     <= 10'd0;
            stage3_y     <= 10'd0;
            stage3_sum   <= 14'd0;

            stage4_valid <= 1'b0;
            stage4_last  <= 1'b0;
            stage4_data  <= 8'd0;
        end
        else if (pipeline_advance) begin
            // 和RAM输出对齐
            read_valid     <= issue_valid;
            read_mem_valid <= issue_mem_read;
            read_mem_write <= issue_mem_write;
            read_x         <= issue_x;
            read_y         <= issue_y;
            read_current   <= issue_current;

            // 窗口推进一列。非阻塞赋值，下面读到的仍是更新前的两列
            if (read_valid) begin
                w01 <= w02; w02 <= step_upper;
                w11 <= w12; w12 <= step_middle;
                w21 <= w22; w22 <= read_current;
            end

            // 第1级：窗口中心是(read_x-1, read_y-1)
            // 先收到下一行、下一列，才能凑齐中心像素的邻域
            stage1_valid <= read_valid && (read_x >= 1) && (read_y >= 1);
            if (read_valid && (read_x >= 1) && (read_y >= 1)) begin
                stage1_x    <= read_x - 10'd1;
                stage1_y    <= read_y - 10'd1;
                stage1_last <= (read_x == WIDTH) && (read_y == HEIGHT);
                stage1_p00 <= w01; stage1_p01 <= w02; stage1_p02 <= step_upper;
                stage1_p10 <= w11; stage1_p12 <= step_middle;
                stage1_p20 <= w21; stage1_p21 <= w22; stage1_p22 <= read_current;
            end

            // 第2级：两方向梯度
            stage2_valid <= stage1_valid;
            if (stage1_valid) begin
                stage2_x    <= stage1_x;
                stage2_y    <= stage1_y;
                stage2_last <= stage1_last;
                stage2_gx   <= gx_next;
                stage2_gy   <= gy_next;
            end

            // 第3级：梯度绝对值求和
            stage3_valid <= stage2_valid;
            if (stage2_valid) begin
                stage3_x    <= stage2_x;
                stage3_y    <= stage2_y;
                stage3_last <= stage2_last;
                stage3_sum  <= sum_next;
            end

            // 第4级：边界强制为0，其余按80二值化
            stage4_valid <= stage3_valid;
            if (stage3_valid) begin
                stage4_last <= stage3_last;
                stage4_data <= stage3_interior && (mag_sat_next >= EDGE_THRESHOLD) ? 8'd255 : 8'd0;
            end

            // 一行输入结束后补右列，整帧结束后再补最后一行
            case (state)
                ST_INPUT: begin
                    if (input_fire) begin
                        if (input_x == WIDTH - 1) begin
                            input_x <= 10'd0;
                            state   <= ST_PAD_COLUMN;
                        end
                        else begin
                            input_x <= input_x + 10'd1;
                        end
                    end
                end

                ST_PAD_COLUMN: begin
                    if (input_y == HEIGHT - 1) begin
                        pad_x <= 10'd0;
                        state <= ST_PAD_ROW;
                    end
                    else begin
                        input_y <= input_y + 10'd1;
                        state   <= ST_INPUT;
                    end
                end

                default: begin // ST_PAD_ROW
                    if (pad_x == WIDTH) begin
                        pad_x   <= 10'd0;
                        input_x <= 10'd0;
                        input_y <= 10'd0;
                        state   <= ST_INPUT;
                    end
                    else begin
                        pad_x <= pad_x + 10'd1;
                    end
                end
            endcase
        end
    end

endmodule

