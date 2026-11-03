// 对 8x6 个网格做四连通搜索，找出活跃格子最多的一块
// 输入按行接收48个计数，输出 x、y、w、h、活跃格数、面积缩减率
`timescale 1ns / 1ps
module roi_engine
(
    input aclk,
    input aresetn,

    // 来自 grid_counter 的 48 个 16-bit 计数
    input [15:0] s_axis_tdata,
    input s_axis_tvalid,
    output wire s_axis_tready,
    input s_axis_tlast,

    // 依次输出 6 个 16-bit ROI 字段
    output reg [15:0] m_axis_tdata,
    output wire m_axis_tvalid,
    input m_axis_tready,
    output wire m_axis_tlast,

    input [15:0] active_threshold
);

    localparam integer GRID_COLUMNS = 8;
    localparam integer GRID_ROWS    = 6;
    localparam integer GRID_COUNT   = GRID_COLUMNS * GRID_ROWS;
    localparam integer OUTPUT_WORDS = 6;

    // 每个字节对应一个网格行；bit0/bit7 分别是该行的第0/7列
    localparam [47:0] COL0_MASK = 48'h010101010101;
    localparam [47:0] COL7_MASK = 48'h808080808080;

    // 下标是包围框占的格子数，表值为 (1 - 格子数/48) * 10000。
    localparam [15:0] REDUCTION_LUT [0:48] = '{
        16'd10000, 16'd9792, 16'd9583, 16'd9375, 16'd9167,
        16'd8958,  16'd8750, 16'd8542, 16'd8333, 16'd8125,
        16'd7917,  16'd7708, 16'd7500, 16'd7292, 16'd7083,
        16'd6875,  16'd6667, 16'd6458, 16'd6250, 16'd6042,
        16'd5833,  16'd5625, 16'd5417, 16'd5208, 16'd5000,
        16'd4792,  16'd4583, 16'd4375, 16'd4167, 16'd3958,
        16'd3750,  16'd3542, 16'd3333, 16'd3125, 16'd2917,
        16'd2708,  16'd2500, 16'd2292, 16'd2083, 16'd1875,
        16'd1667,  16'd1458, 16'd1250, 16'd1042, 16'd833,
        16'd625,   16'd417,  16'd208,  16'd0
    };

    // 接收计数 -> 遍历连通区域 -> 换算像素坐标 -> 输出六字段
    localparam [2:0] ST_RECEIVE_COUNTS = 3'd0;
    localparam [2:0] ST_INIT           = 3'd1;
    localparam [2:0] ST_EXPAND_LOOP    = 3'd2;
    localparam [2:0] ST_EXPAND_ITER    = 3'd3;
    localparam [2:0] ST_COMPARE_BEST   = 3'd4;
    localparam [2:0] ST_COMPUTE_OUTPUT = 3'd5;
    localparam [2:0] ST_OUTPUT         = 3'd6;

    reg [2:0] state;

    reg [5:0] count_index;
    reg [2:0] output_index;

    reg [47:0] active_map;     // 这一帧所有活跃格子
    reg [47:0] unvisited_map;  // 还没搜索过的活跃格子
    reg [47:0] component_map;  // 当前区域已经收进来的格子
    reg [47:0] frontier_map;   // 这一轮准备收进来的格子

    reg [5:0] component_size;
    reg [5:0] best_size;

    // 搜索时先记网格坐标，最后统一换成像素坐标
    reg [2:0] comp_min_x, comp_max_x;
    reg [2:0] comp_min_y, comp_max_y;
    reg [2:0] best_min_x, best_max_x;
    reg [2:0] best_min_y, best_max_y;

    reg [15:0] roi_x;
    reg [15:0] roi_y;
    reg [15:0] roi_w;
    reg [15:0] roi_h;
    reg [15:0] best_grids;
    reg [15:0] reduction_x100;

    reg seed_found;
    reg [5:0] seed_index;

    wire [47:0] neighbor_map;
    wire [47:0] new_frontier;
    wire [47:0] remaining_map;

    wire [7:0] frontier_col_has;
    wire [5:0] frontier_row_has;
    reg [2:0] frontier_min_x, frontier_max_x;
    reg [2:0] frontier_min_y, frontier_max_y;

    wire [3:0] frontier_count0, frontier_count1, frontier_count2;
    wire [3:0] frontier_count3, frontier_count4, frontier_count5;
    wire [4:0] frontier_count01, frontier_count23, frontier_count45;
    wire [5:0] frontier_count0123;
    wire [5:0] frontier_popcount;

    wire [3:0] best_span_x;
    wire [3:0] best_span_y;
    reg [6:0] bbox_grid_count;
    reg [6:0] bbox_grid_count_reg;
    reg compute_phase;

    integer seed_scan;
    integer bound_scan;

    function automatic [3:0] popcount8(input [7:0] value);
        reg [1:0] pair0, pair1, pair2, pair3;
        reg [2:0] quad0, quad1;
        begin
            pair0 = {1'b0, value[0]} + {1'b0, value[1]};
            pair1 = {1'b0, value[2]} + {1'b0, value[3]};
            pair2 = {1'b0, value[4]} + {1'b0, value[5]};
            pair3 = {1'b0, value[6]} + {1'b0, value[7]};
            quad0 = {1'b0, pair0} + {1'b0, pair1};
            quad1 = {1'b0, pair2} + {1'b0, pair3};
            popcount8 = {1'b0, quad0} + {1'b0, quad1};
        end
    endfunction

    // 网格坐标转像素坐标：乘80等于乘64加乘16
    function automatic [15:0] scale_by_80(input [3:0] value);
        reg [15:0] extended_value;
        begin
            extended_value = {12'd0, value};
            scale_by_80 = (extended_value << 6) + (extended_value << 4);
        end
    endfunction

    assign s_axis_tready = aresetn && (state == ST_RECEIVE_COUNTS);
    assign m_axis_tvalid = aresetn && (state == ST_OUTPUT);
    assign m_axis_tlast  = m_axis_tvalid&& (output_index == OUTPUT_WORDS - 1);

    always @* begin
        case (output_index)
            3'd0: m_axis_tdata = roi_x;
            3'd1: m_axis_tdata = roi_y;
            3'd2: m_axis_tdata = roi_w;
            3'd3: m_axis_tdata = roi_h;
            3'd4: m_axis_tdata = best_grids;
            default: m_axis_tdata = reduction_x100;
        endcase
    end

    // 从低位找第一个未访问格子，作为下一块区域的起点
    always @* begin
        seed_found = 1'b0;
        seed_index = 6'd0;
        for (seed_scan = 0; seed_scan < GRID_COUNT;
             seed_scan = seed_scan + 1) begin
            if (!seed_found && unvisited_map[seed_scan])
             begin
                seed_found = 1'b1;
                seed_index = seed_scan[5:0];
             end
        end
    end

    // 上下移动8位，左右移动1位。左右还要屏蔽跨行的那一位
    assign neighbor_map = (frontier_map >> 8) | (frontier_map << 8) | ((frontier_map >> 1) & ~COL7_MASK) | ((frontier_map << 1) & ~COL0_MASK);

    // 只留下活跃且尚未收进本区域的邻居，作为下一轮前沿
    assign new_frontier = neighbor_map& active_map& ~(component_map | frontier_map);
    
    assign remaining_map = unvisited_map & ~component_map;

    // 统计本轮新增格子数，分组相加
    assign frontier_count0 = popcount8(frontier_map[7:0]);
    assign frontier_count1 = popcount8(frontier_map[15:8]);
    assign frontier_count2 = popcount8(frontier_map[23:16]);
    assign frontier_count3 = popcount8(frontier_map[31:24]);
    assign frontier_count4 = popcount8(frontier_map[39:32]);
    assign frontier_count5 = popcount8(frontier_map[47:40]);
    assign frontier_count01 = {1'b0, frontier_count0}
                            + {1'b0, frontier_count1};
    assign frontier_count23 = {1'b0, frontier_count2}
                            + {1'b0, frontier_count3};
    assign frontier_count45 = {1'b0, frontier_count4}
                            + {1'b0, frontier_count5};
    assign frontier_count0123 = {1'b0, frontier_count01}
                              + {1'b0, frontier_count23};
    assign frontier_popcount = frontier_count0123
                             + {1'b0, frontier_count45};

    // 当前前沿覆盖了哪些列和行，用于更新区域包围框
    genvar column_index;
    generate
        for (column_index = 0; column_index < GRID_COLUMNS;
             column_index = column_index + 1) begin : gen_frontier_columns
            assign frontier_col_has[column_index] = |(frontier_map & (COL0_MASK << column_index));
        end
    endgenerate

    assign frontier_row_has[0] = |frontier_map[7:0];
    assign frontier_row_has[1] = |frontier_map[15:8];
    assign frontier_row_has[2] = |frontier_map[23:16];
    assign frontier_row_has[3] = |frontier_map[31:24];
    assign frontier_row_has[4] = |frontier_map[39:32];
    assign frontier_row_has[5] = |frontier_map[47:40];

    always @* begin
        frontier_min_x = 3'd7;
        frontier_max_x = 3'd0;
        frontier_min_y = 3'd5;
        frontier_max_y = 3'd0;

        // 反向扫描后留下最低坐标，正向扫描后留下最高坐标
        for (bound_scan = GRID_COLUMNS - 1; bound_scan >= 0;
             bound_scan = bound_scan - 1) begin
            if (frontier_col_has[bound_scan])
                frontier_min_x = bound_scan[2:0];
        end
        for (bound_scan = 0; bound_scan < GRID_COLUMNS;
             bound_scan = bound_scan + 1) begin
            if (frontier_col_has[bound_scan])
                frontier_max_x = bound_scan[2:0];
        end
        for (bound_scan = GRID_ROWS - 1; bound_scan >= 0;
             bound_scan = bound_scan - 1) begin
            if (frontier_row_has[bound_scan])
                frontier_min_y = bound_scan[2:0];
        end
        for (bound_scan = 0; bound_scan < GRID_ROWS;
             bound_scan = bound_scan + 1) begin
            if (frontier_row_has[bound_scan])
                frontier_max_y = bound_scan[2:0];
        end
    end

    assign best_span_x = {1'b0, best_max_x} - {1'b0, best_min_x} + 4'd1;
    assign best_span_y = {1'b0, best_max_y} - {1'b0, best_min_y} + 4'd1;
   
    always @* begin
        case (best_span_y)
            4'd1: bbox_grid_count = {3'd0, best_span_x};
            4'd2: bbox_grid_count = ({3'd0, best_span_x} << 1);
            4'd3: bbox_grid_count = ({3'd0, best_span_x} << 1) + {3'd0, best_span_x};
            4'd4: bbox_grid_count = ({3'd0, best_span_x} << 2);
            4'd5: bbox_grid_count = ({3'd0, best_span_x} << 2) + {3'd0, best_span_x};
            4'd6: bbox_grid_count = ({3'd0, best_span_x} << 2) + ({3'd0, best_span_x} << 1);
            default: bbox_grid_count = 7'd0;
        endcase
    end

    always @(posedge aclk) begin
        if (!aresetn) begin
            state           <= ST_RECEIVE_COUNTS;
            count_index     <= 6'd0;
            output_index    <= 3'd0;
            active_map      <= 48'd0;
            unvisited_map   <= 48'd0;
            component_map   <= 48'd0;
            frontier_map    <= 48'd0;
            component_size  <= 6'd0;
            best_size       <= 6'd0;
            comp_min_x      <= 3'd0;
            comp_max_x      <= 3'd0;
            comp_min_y      <= 3'd0;
            comp_max_y      <= 3'd0;
            best_min_x      <= 3'd0;
            best_max_x      <= 3'd0;
            best_min_y      <= 3'd0;
            best_max_y      <= 3'd0;
            roi_x           <= 16'd0;
            roi_y           <= 16'd0;
            roi_w           <= 16'd0;
            roi_h           <= 16'd0;
            best_grids      <= 16'd0;
            reduction_x100  <= 16'd10000;
            bbox_grid_count_reg <= 7'd0;
            compute_phase    <= 1'b0;
        end
        else begin
            case (state)
                ST_RECEIVE_COUNTS: begin
                    if (s_axis_tvalid && s_axis_tready) begin
                        active_map[count_index] <= (s_axis_tdata > active_threshold);


                        if (count_index == GRID_COUNT - 1) begin
                            count_index <= 6'd0;
                            state       <= ST_INIT;
                        end
                        else count_index <= count_index + 6'd1;
                    end
                end

                ST_INIT: begin
                    // 前一拍对 active_map[47] 的写入此时已经生效
                    unvisited_map  <= active_map;
                    component_map  <= 48'd0;
                    frontier_map   <= 48'd0;
                    component_size <= 6'd0;
                    best_size      <= 6'd0;
                    best_min_x     <= 3'd0;
                    best_max_x     <= 3'd0;
                    best_min_y     <= 3'd0;
                    best_max_y     <= 3'd0;
                    compute_phase  <= 1'b0;
                    state          <= ST_EXPAND_LOOP;
                end

                ST_EXPAND_LOOP: begin
                    if (!seed_found) begin
                        // 没有活跃网格，或所有区域都已经处理完成
                        state <= ST_COMPUTE_OUTPUT;
                    end
                    else begin
                        component_map  <= 48'd0;
                        frontier_map   <= (48'b1 << seed_index);
                        component_size <= 6'd0;
                        comp_min_x <= seed_index[2:0];
                        comp_max_x <= seed_index[2:0];
                        comp_min_y <= seed_index[5:3];
                        comp_max_y <= seed_index[5:3];
                        state          <= ST_EXPAND_ITER;
                    end
                end

                ST_EXPAND_ITER: begin
                    // 收进本轮前沿，同时更新当前区域的大小和边界
                    component_map  <= component_map | frontier_map;
                    component_size <= component_size + frontier_popcount;

                    if (frontier_min_x < comp_min_x)
                        comp_min_x <= frontier_min_x;
                    if (frontier_max_x > comp_max_x)
                        comp_max_x <= frontier_max_x;
                    if (frontier_min_y < comp_min_y)
                        comp_min_y <= frontier_min_y;
                    if (frontier_max_y > comp_max_y)
                        comp_max_y <= frontier_max_y;

                    if (new_frontier == 48'd0) begin
                        frontier_map <= 48'd0;
                        state        <= ST_COMPARE_BEST;
                    end
                    else begin
                        frontier_map <= new_frontier;
                    end
                end

                ST_COMPARE_BEST: begin
                    if (component_size > best_size) begin
                        best_size  <= component_size;
                        best_min_x <= comp_min_x;
                        best_max_x <= comp_max_x;
                        best_min_y <= comp_min_y;
                        best_max_y <= comp_max_y;
                    end

                    unvisited_map <= remaining_map;
                    if (remaining_map != 48'd0)
                        state <= ST_EXPAND_LOOP;
                    else
                        state <= ST_COMPUTE_OUTPUT;
                end

                ST_COMPUTE_OUTPUT: begin
                    // 分两拍：先寄存包围框面积，再用它查询缩减率
                    if (!compute_phase) begin
                        if (best_size == 6'd0) begin
                            roi_x               <= 16'd0;
                            roi_y               <= 16'd0;
                            roi_w               <= 16'd0;
                            roi_h               <= 16'd0;
                            best_grids          <= 16'd0;
                            bbox_grid_count_reg <= 7'd0;
                        end
                        else begin
                            roi_x               <= scale_by_80({1'b0, best_min_x});
                            roi_y               <= scale_by_80({1'b0, best_min_y});
                            roi_w               <= scale_by_80(best_span_x);
                            roi_h               <= scale_by_80(best_span_y);
                            best_grids          <= {10'd0, best_size};
                            bbox_grid_count_reg <= bbox_grid_count;
                        end

                        compute_phase <= 1'b1;
                    end
                    else begin
                        reduction_x100 <= REDUCTION_LUT[bbox_grid_count_reg];
                        output_index   <= 3'd0;
                        compute_phase  <= 1'b0;
                        state          <= ST_OUTPUT;
                    end
                end

                ST_OUTPUT: begin
                    if (m_axis_tvalid && m_axis_tready) begin
                        if (output_index == OUTPUT_WORDS - 1) begin
                            output_index   <= 3'd0;
                            active_map     <= 48'd0;
                            unvisited_map  <= 48'd0;
                            component_map  <= 48'd0;
                            frontier_map   <= 48'd0;
                            state          <= ST_RECEIVE_COUNTS;
                        end
                        else begin
                            output_index <= output_index + 3'd1;
                        end
                    end
                end

                default: begin
                    state          <= ST_RECEIVE_COUNTS;
                    count_index    <= 6'd0;
                    output_index   <= 3'd0;
                    active_map     <= 48'd0;
                    unvisited_map  <= 48'd0;
                    component_map  <= 48'd0;
                    frontier_map   <= 48'd0;
                    component_size <= 6'd0;
                    best_size      <= 6'd0;
                    compute_phase  <= 1'b0;
                end
            endcase
        end
    end

endmodule
