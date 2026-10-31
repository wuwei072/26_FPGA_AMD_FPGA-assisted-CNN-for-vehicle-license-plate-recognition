`timescale 1ns / 1ps

module tb_roi_engine;

    localparam integer GRID_COUNT   = 48;
    localparam integer OUTPUT_WORDS = 6;
    localparam integer MAIN_FRAMES  = 2;
    localparam integer TOTAL_FRAMES = 3; // 第3帧为内部生成的平局规则定向测试

    localparam [15:0] EXPECTED_OUTPUT [0:OUTPUT_WORDS-1] = '{
        16'd160,  // roi_x
        16'd160,  // roi_y
        16'd160,  // roi_w
        16'd160,  // roi_h
        16'd4,    // best_grids
        16'd9167  // reduction_x100 = 91.67%
    };

    reg          aclk;
    reg          aresetn;

    reg   [15:0] s_axis_tdata;
    reg          s_axis_tvalid;
    wire         s_axis_tready;
    reg          s_axis_tlast;

    wire  [15:0] m_axis_tdata;
    wire         m_axis_tvalid;
    reg          m_axis_tready;
    wire         m_axis_tlast;

    reg   [15:0] counts_mem [0:GRID_COUNT-1];
    reg   [15:0] observed [0:TOTAL_FRAMES-1][0:OUTPUT_WORDS-1];

    integer received [0:TOTAL_FRAMES-1];
    integer mismatches [0:TOTAL_FRAMES-1];
    integer tlast_bad [0:TOTAL_FRAMES-1];
    integer output_frame;
    integer output_index;
    integer ready_cycle;
    integer handshake_bad;

    reg   [15:0] stalled_data;
    reg          stalled_last;
    reg          was_stalled;

    function automatic [15:0] expected_word(
        input integer frame_number,
        input integer field_number
    );
        begin
            if (frame_number < MAIN_FRAMES) begin
                expected_word = EXPECTED_OUTPUT[field_number];
            end
            else begin
                // 三个等大的2格区域：优先选择最上、再最左的(0,0)-(1,0)
                case (field_number)
                    0: expected_word = 16'd0;
                    1: expected_word = 16'd0;
                    2: expected_word = 16'd160;
                    3: expected_word = 16'd80;
                    4: expected_word = 16'd2;
                    default: expected_word = 16'd9583;
                endcase
            end
        end
    endfunction

    function automatic [15:0] tie_count(input integer grid_index);
        begin
            // 上方左、上方右、下方左各放一个大小为2的区域
            // index47恰好等于阈值，用于同时验证严格大于768
            case (grid_index)
                0, 1, 5, 6, 32, 33: tie_count = 16'd769;
                47: tie_count = 16'd768;
                default: tie_count = 16'd0;
            endcase
        end
    endfunction

    roi_engine dut (
        .aclk             (aclk),
        .aresetn          (aresetn),
        .s_axis_tdata     (s_axis_tdata),
        .s_axis_tvalid    (s_axis_tvalid),
        .s_axis_tready    (s_axis_tready),
        .s_axis_tlast     (s_axis_tlast),
        .m_axis_tdata     (m_axis_tdata),
        .m_axis_tvalid    (m_axis_tvalid),
        .m_axis_tready    (m_axis_tready),
        .m_axis_tlast     (m_axis_tlast),
        .active_threshold (16'd768)
    );

    initial begin
        aclk = 1'b0;
        forever #5 aclk = ~aclk;
    end

    // 每5拍制造1拍输出反压。
    always @(negedge aclk) begin
        if (!aresetn) begin
            ready_cycle   <= 0;
            m_axis_tready <= 1'b0;
        end
        else begin
            ready_cycle   <= ready_cycle + 1;
            m_axis_tready <= ((ready_cycle % 5) != 0);
        end
    end

    // 接收并检查6个ROI字段，同时验证反压期间TVALID/TDATA/TLAST稳定
    always @(posedge aclk) begin
        if (!aresetn) begin
            output_frame  <= 0;
            output_index  <= 0;
            handshake_bad <= 0;
            was_stalled   <= 1'b0;
            stalled_data  <= 16'd0;
            stalled_last  <= 1'b0;
        end
        else begin
            if (was_stalled) begin
                if (m_axis_tvalid !== 1'b1 || m_axis_tdata !== stalled_data || m_axis_tlast !== stalled_last) begin
                    $display("FAIL: AXI output changed while stalled");
                    handshake_bad <= handshake_bad + 1;
                end
            end

            was_stalled <= m_axis_tvalid && !m_axis_tready;
            if (m_axis_tvalid && !m_axis_tready) begin
                stalled_data <= m_axis_tdata;
                stalled_last <= m_axis_tlast;
            end

            if (m_axis_tvalid && m_axis_tready) begin
                if (output_frame >= TOTAL_FRAMES) begin
                    $display("FAIL: received an unexpected extra ROI word");
                    $fatal(1);
                end

                observed[output_frame][output_index] <= m_axis_tdata;
                received[output_frame] <= received[output_frame] + 1;

                if (m_axis_tdata !== expected_word(output_frame, output_index)) begin
                    $display("Frame %0d field %0d mismatch: got=%0d expected=%0d",
                             output_frame + 1, output_index,
                             m_axis_tdata,
                             expected_word(output_frame, output_index));
                    mismatches[output_frame] <= mismatches[output_frame] + 1;
                end

                if (m_axis_tlast !== (output_index == OUTPUT_WORDS - 1)) begin
                    $display("Frame %0d field %0d TLAST mismatch: got=%b expected=%b",
                             output_frame + 1, output_index, m_axis_tlast,
                             (output_index == OUTPUT_WORDS - 1));
                    tlast_bad[output_frame] <= tlast_bad[output_frame] + 1;
                end

                if (output_index == OUTPUT_WORDS - 1) begin
                    output_index <= 0;
                    output_frame <= output_frame + 1;
                end
                else begin
                    output_index <= output_index + 1;
                end
            end
        end
    end

    task automatic load_counts;
        string counts_path;
        integer fd;
        integer scan_result;
        integer index;
        reg   [15:0] extra_word;
        begin
            if (!$value$plusargs("COUNTS=%s", counts_path)) begin
                counts_path = "../../../../../../sim/vectors/single_target_640x480_grid_counts.hex";
                fd = $fopen(counts_path, "r");
                if (fd == 0) begin
                    counts_path = "hardware/sim/vectors/single_target_640x480_grid_counts.hex";
                end
                else begin
                    $fclose(fd);
                end
            end

            fd = $fopen(counts_path, "r");
            if (fd == 0) begin
                $display("ERROR: cannot open %s", counts_path);
                $fatal(1);
            end

            for (index = 0; index < GRID_COUNT; index = index + 1) begin
                scan_result = $fscanf(fd, "%h", counts_mem[index]);
                if (scan_result != 1) begin
                    $display("ERROR: %s contains fewer than %0d valid counts",
                             counts_path, GRID_COUNT);
                    $fclose(fd);
                    $fatal(1);
                end
            end

            // 文件必须恰好包含48个十六进制计数，避免多余数据被静默忽略
            scan_result = $fscanf(fd, "%h", extra_word);
            if (scan_result == 1) begin
                $display("ERROR: %s contains more than %0d counts",
                         counts_path, GRID_COUNT);
                $fclose(fd);
                $fatal(1);
            end
            $fclose(fd);
        end
    endtask

    // 两帧之间不主动插入空拍；DUT拉低TREADY时保持输入不变
    task automatic send_two_frames;
        integer frame;
        integer index;
        begin
            s_axis_tvalid = 1'b0;
            s_axis_tdata  = 16'd0;
            s_axis_tlast  = 1'b0;
            @(negedge aclk);

            for (frame = 0; frame < MAIN_FRAMES; frame = frame + 1) begin
                for (index = 0; index < GRID_COUNT; index = index + 1) begin
                    s_axis_tvalid = 1'b1;
                    s_axis_tdata  = counts_mem[index];
                    s_axis_tlast  = (index == GRID_COUNT - 1);
                    do @(posedge aclk); while (s_axis_tready !== 1'b1);
                    @(negedge aclk);
                end
            end

            // 追加一帧定向平局用例，不改变要求的两帧single_target输出格式
            for (index = 0; index < GRID_COUNT; index = index + 1) begin
                s_axis_tvalid = 1'b1;
                s_axis_tdata  = tie_count(index);
                s_axis_tlast  = (index == GRID_COUNT - 1);
                do @(posedge aclk); while (s_axis_tready !== 1'b1);
                @(negedge aclk);
            end

            s_axis_tvalid = 1'b0;
            s_axis_tdata  = 16'd0;
            s_axis_tlast  = 1'b0;
        end
    endtask

    initial begin : test_sequence
        integer frame;
        integer field;
        integer timeout_cycles;
        integer total_mismatches;
        integer total_tlast_bad;

        load_counts();

        for (frame = 0; frame < TOTAL_FRAMES; frame = frame + 1) begin
            received[frame]   = 0;
            mismatches[frame] = 0;
            tlast_bad[frame]  = 0;
            for (field = 0; field < OUTPUT_WORDS; field = field + 1)
                observed[frame][field] = 16'd0;
        end

        aresetn       = 1'b0;
        s_axis_tvalid = 1'b0;
        s_axis_tdata  = 16'd0;
        s_axis_tlast  = 1'b0;
        m_axis_tready = 1'b0;

        repeat (6) @(posedge aclk);
        @(negedge aclk);
        aresetn = 1'b1;

        fork
            send_two_frames();
            begin
                timeout_cycles = 0;
                while (output_frame < TOTAL_FRAMES
                       && timeout_cycles < 5000) begin
                    @(posedge aclk);
                    timeout_cycles = timeout_cycles + 1;
                end
                if (output_frame < TOTAL_FRAMES) begin
                    $display("FAIL: timeout, completed frames=%0d", output_frame);
                    $fatal(1);
                end
            end
        join

        // 留出几个周期检查是否出现第7项或额外帧输出
        repeat (6) @(posedge aclk);

        total_mismatches = mismatches[0] + mismatches[1] + mismatches[2];
        total_tlast_bad  = tlast_bad[0] + tlast_bad[1] + tlast_bad[2];

        for (frame = 0; frame < MAIN_FRAMES; frame = frame + 1) begin
            $display("Frame %0d: ROI=(%0d,%0d,%0d,%0d), best_grids=%0d, reduction=%0d.%02d%%, mismatches=%0d",
                     frame + 1,
                     observed[frame][0], observed[frame][1],
                     observed[frame][2], observed[frame][3],
                     observed[frame][4],
                     observed[frame][5] / 100,
                     observed[frame][5] % 100,
                     mismatches[frame]);
        end

        if (received[0] == OUTPUT_WORDS
            && received[1] == OUTPUT_WORDS
            && received[2] == OUTPUT_WORDS
            && output_frame == TOTAL_FRAMES
            && total_mismatches == 0
            && total_tlast_bad == 0
            && handshake_bad == 0) begin
            $display("PASS");
        end
        else begin
            $display("FAIL: received=%0d/%0d mismatches=%0d tlast_bad=%0d handshake_bad=%0d",
                     received[0], received[1], total_mismatches,
                     total_tlast_bad, handshake_bad);
            $fatal(1);
        end

        $finish;
    end

endmodule
