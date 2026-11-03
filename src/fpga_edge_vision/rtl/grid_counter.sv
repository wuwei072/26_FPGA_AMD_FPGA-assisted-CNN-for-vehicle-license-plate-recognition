// 把 640x480 边缘图分成 8x6 格，每格 80x80
// 先累计当前 80 行的8格，存好后继续下一带，最后依次输出48个计数
`timescale 1ns / 1ps
module grid_counter 
(
    input aclk,
    input aresetn,

    input [7:0] s_axis_tdata,
    input s_axis_tvalid,
    output wire s_axis_tready,
    input s_axis_tlast,

    output wire [15:0] m_axis_tdata,
    output wire m_axis_tvalid,
    input m_axis_tready,
    output wire m_axis_tlast,

    input [15:0] threshold,
    input enable
);

    localparam integer GRID_WIDTH = 80;
    localparam integer GRID_HEIGHT = 80;
    localparam integer GRID_COUNT = 48;
    localparam ST_RECEIVE = 1'b0,
               ST_OUTPUT = 1'b1;
    reg state;
    // 像素在格子里的位置，以及格子在整张图里的位置
    reg [6:0] x_in_grid;
    reg [6:0] y_in_grid;
    reg [2:0] grid_x;
    reg [2:0] grid_y;

    // 留住上一拍的网格行，用它选择这一带计数的存放位置
    reg [2:0] grid_y_prev;

    // row_acc只管当前80行，grid_counts存整帧的结果
    reg [15:0] row_acc [0:7];

    reg [15:0] grid_counts [0:GRID_COUNT-1];
    reg [5:0] output_idx;

    wire edge_hit;
    wire band_last_pixel;

    integer clear_index;
    integer save_index;

    assign edge_hit = enable && ({8'd0, s_axis_tdata} >= threshold);

    // 一带80行的最后一个像素
    assign band_last_pixel = (x_in_grid == GRID_WIDTH - 1)   && (grid_x == 3'd7) && (y_in_grid == GRID_HEIGHT - 1);

    // 输出计数时先不接下一帧；只有握手才移动输出索引
    assign s_axis_tready = aresetn && (state == ST_RECEIVE);

    assign m_axis_tvalid = aresetn && (state == ST_OUTPUT);
    assign m_axis_tdata = grid_counts[output_idx];
    assign m_axis_tlast = m_axis_tvalid && (output_idx == GRID_COUNT - 1);

    always @(posedge aclk) begin
        if (!aresetn) begin
            state <= ST_RECEIVE;
            x_in_grid <= 7'd0;
            y_in_grid <= 7'd0;
            grid_x <= 3'd0;
            grid_y <= 3'd0;
            grid_y_prev <= 3'd0;
            output_idx <= 6'd0;

            for (clear_index = 0; clear_index < 8; clear_index = clear_index + 1) begin
                row_acc[clear_index] <= 16'd0;
            end

            for (clear_index = 0; clear_index < GRID_COUNT; clear_index = clear_index + 1) begin
                grid_counts[clear_index] <= 16'd0;
            end
        end
        else begin
            case (state)
                ST_RECEIVE: begin
                    if (s_axis_tvalid && s_axis_tready) begin
                        grid_y_prev <= grid_y;

                        if (s_axis_tlast) begin
                            for (save_index = 0; save_index < 7; save_index = save_index + 1)
                                grid_counts[40 + save_index] <= row_acc[save_index];
                            grid_counts[47] <= row_acc[7] + (edge_hit ? 16'd1 : 16'd0);
                            for (save_index = 0; save_index < 8; save_index = save_index + 1)
                                row_acc[save_index] <= 16'd0;

                            x_in_grid <= 7'd0;
                            y_in_grid <= 7'd0;
                            grid_x <= 3'd0;
                            grid_y <= 3'd0;
                            grid_y_prev <= 3'd0;
                            output_idx <= 6'd0;
                            state <= ST_OUTPUT;
                        end
                        else begin
                            if (band_last_pixel) begin
                                case (grid_y_prev)
                                    3'd0: begin
                                        for (save_index = 0; save_index < 7; save_index = save_index + 1)
                                            grid_counts[save_index] <= row_acc[save_index];
                                        grid_counts[7] <= row_acc[7] + (edge_hit ? 16'd1 : 16'd0);
                                          end
                                    3'd1: begin
                                        for (save_index = 0; save_index < 7; save_index = save_index + 1)
                                            grid_counts[8 + save_index] <= row_acc[save_index];
                                        grid_counts[15] <= row_acc[7] + (edge_hit ? 16'd1 : 16'd0);
                                          end
                                    3'd2: begin
                                        for (save_index = 0; save_index < 7; save_index = save_index + 1)
                                            grid_counts[16 + save_index] <= row_acc[save_index];
                                        grid_counts[23] <= row_acc[7] + (edge_hit ? 16'd1 : 16'd0);
                                          end
                                    3'd3: begin
                                        for (save_index = 0; save_index < 7; save_index = save_index + 1)
                                            grid_counts[24 + save_index] <= row_acc[save_index];
                                        grid_counts[31] <= row_acc[7] + (edge_hit ? 16'd1 : 16'd0);
                                          end
                                    3'd4: begin
                                        for (save_index = 0; save_index < 7; save_index = save_index + 1)
                                            grid_counts[32 + save_index] <= row_acc[save_index];
                                        grid_counts[39] <= row_acc[7] + (edge_hit ? 16'd1 : 16'd0);
                                          end
                                    default: begin
                                        // 第6带在上面的TLAST分支保存
                                    end
                                endcase

                                for (clear_index = 0; clear_index < 8; clear_index = clear_index + 1) begin
                                    row_acc[clear_index] <= 16'd0;
                                end
                            end
                            else if (edge_hit) begin
                                case (grid_x)
                                    3'd0: row_acc[0] <= row_acc[0] + 16'd1;
                                    3'd1: row_acc[1] <= row_acc[1] + 16'd1;
                                    3'd2: row_acc[2] <= row_acc[2] + 16'd1;
                                    3'd3: row_acc[3] <= row_acc[3] + 16'd1;
                                    3'd4: row_acc[4] <= row_acc[4] + 16'd1;
                                    3'd5: row_acc[5] <= row_acc[5] + 16'd1;
                                    3'd6: row_acc[6] <= row_acc[6] + 16'd1;
                                    default: row_acc[7] <= row_acc[7] + 16'd1;
                                endcase
                            end

                            if (x_in_grid == GRID_WIDTH - 1) begin
                                x_in_grid <= 7'd0;
                                if (grid_x == 3'd7) begin
                                    grid_x <= 3'd0;
                                    if (y_in_grid == GRID_HEIGHT - 1) begin
                                        y_in_grid <= 7'd0;
                                        grid_y <= grid_y + 3'd1;
                                    end
                                    else begin
                                        y_in_grid <= y_in_grid + 7'd1;
                                    end
                                end
                                else begin
                                    grid_x <= grid_x + 3'd1;
                                end
                            end
                            else begin
                                x_in_grid <= x_in_grid + 7'd1;
                            end
                        end
                    end
                end

                default: begin // ST_OUTPUT
                    if (m_axis_tvalid && m_axis_tready) begin
                        if (output_idx == GRID_COUNT - 1)
                         begin
                            output_idx <= 6'd0;
                            state <= ST_RECEIVE;

                            for (clear_index = 0; clear_index < 8; clear_index = clear_index + 1)
                             begin
                                row_acc[clear_index] <= 16'd0;
                             end

                            for (clear_index = 0; clear_index < GRID_COUNT; clear_index = clear_index + 1)
                             begin
                                grid_counts[clear_index] <= 16'd0;
                             end
                         end
                        else begin
                            output_idx <= output_idx + 6'd1;
                        end
                    end
                end
            endcase
        end
    end

endmodule
