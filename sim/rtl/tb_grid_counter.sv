`timescale 1ns / 1ps
module tb_grid_counter;
  
    localparam integer WIDTH      = 640;
    localparam integer HEIGHT     = 480;
    localparam integer NPIX       = WIDTH * HEIGHT;
    localparam integer GRID_COUNT = 48;
    localparam integer FRAMES     = 2;

    reg          aclk;
    reg          aresetn;
    reg   [7:0]  s_axis_tdata;
    reg          s_axis_tvalid;
    wire         s_axis_tready;
    reg          s_axis_tlast;
    wire  [15:0] m_axis_tdata;
    wire         m_axis_tvalid;
    reg          m_axis_tready;
    wire         m_axis_tlast;
    reg   [15:0] threshold;
    reg          enable;

    // edge_mem 为 Python/Sobel Golden 输出；发送时按阈值转换为0或255
    byte unsigned edge_mem [0:NPIX-1];
    reg   [15:0] expected_counts [0:GRID_COUNT-1];

    integer received [0:FRAMES-1];
    integer mismatches [0:FRAMES-1];
    integer tlast_bad [0:FRAMES-1];
    integer output_frame;
    integer output_index;
    integer ready_cycle;
    integer handshake_bad;
    reg   [15:0] stalled_data;
    reg          stalled_last;
    reg          was_stalled;

    grid_counter dut (
        .aclk          (aclk),
        .aresetn       (aresetn),
        .s_axis_tdata  (s_axis_tdata),
        .s_axis_tvalid (s_axis_tvalid),
        .s_axis_tready (s_axis_tready),
        .s_axis_tlast  (s_axis_tlast),
        .m_axis_tdata  (m_axis_tdata),
        .m_axis_tvalid (m_axis_tvalid),
        .m_axis_tready (m_axis_tready),
        .m_axis_tlast  (m_axis_tlast),
        .threshold     (threshold),
        .enable        (enable)
    );

    initial begin
        aclk = 1'b0;
        forever #5 aclk = ~aclk;
    end

    // 周期性制造输出反压，验证计数、VALID、DATA和TLAST保持稳定
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

    always @(posedge aclk) begin
        if (!aresetn) begin
            output_frame <= 0;
            output_index <= 0;
            handshake_bad <= 0;
            was_stalled <= 1'b0;
            stalled_data <= 16'd0;
            stalled_last <= 1'b0;
        end
        else begin
            if (was_stalled) begin
                if (!m_axis_tvalid || m_axis_tdata !== stalled_data || m_axis_tlast !== stalled_last)
                    handshake_bad <= handshake_bad + 1;
            end

            was_stalled <= m_axis_tvalid && !m_axis_tready;
            if (m_axis_tvalid && !m_axis_tready) begin
                stalled_data <= m_axis_tdata;
                stalled_last <= m_axis_tlast;
            end

            if (m_axis_tvalid && m_axis_tready) begin
                received[output_frame] <= received[output_frame] + 1;

                if (m_axis_tdata !== expected_counts[output_index]) begin
                    if (mismatches[output_frame] < 10)
                        $display("Frame %0d grid %0d mismatch: got=%0d expected=%0d",
                                 output_frame + 1, output_index,
                                 m_axis_tdata, expected_counts[output_index]);
                    mismatches[output_frame] <= mismatches[output_frame] + 1;
                end

                if (m_axis_tlast !== (output_index == GRID_COUNT - 1))
                    tlast_bad[output_frame] <= tlast_bad[output_frame] + 1;

                if (output_index == GRID_COUNT - 1) begin
                    output_index <= 0;
                    output_frame <= output_frame + 1;
                end
                else begin
                    output_index <= output_index + 1;
                end
            end
        end
    end

    task automatic load_vectors;
        string edge_path;
        string counts_path;
        integer fd;
        integer count;
        begin
            if (!$value$plusargs("EDGE=%s", edge_path)) begin
                edge_path = "data/hdl_vectors/single_target_640x480_expected.bin";
            end

            if (!$value$plusargs("COUNTS=%s", counts_path)) begin
                counts_path = "data/hdl_vectors/single_target_640x480_grid_counts.hex";
            end

            fd = $fopen(edge_path, "rb");
            if (fd == 0) begin
                $display("ERROR: cannot open %s; use +EDGE=<absolute_path> or sim/run_rtl_sim.tcl", edge_path);
                $fatal(1);
            end
            count = $fread(edge_mem, fd);
            $fclose(fd);
            if (count != NPIX) begin
                $display("ERROR: edge bytes=%0d expected=%0d", count, NPIX);
                $fatal(1);
            end

            fd = $fopen(counts_path, "r");
            if (fd == 0) begin
                $display("ERROR: cannot open %s; use +COUNTS=<absolute_path> or sim/run_rtl_sim.tcl", counts_path);
                $fatal(1);
            end
            $fclose(fd);
            $readmemh(counts_path, expected_counts);
        end
    endtask

    // 连续呈现两帧；模块输出48项期间必须反压并保持下一帧首像素
    task automatic send_two_frames;
        integer frame;
        integer index;
        begin
            s_axis_tvalid = 1'b0;
            s_axis_tdata  = 8'd0;
            s_axis_tlast  = 1'b0;
            @(negedge aclk);

            for (frame = 0; frame < FRAMES; frame = frame + 1) begin
                for (index = 0; index < NPIX; index = index + 1) begin
                    s_axis_tvalid = 1'b1;
                    s_axis_tdata  = (edge_mem[index] >= threshold[7:0]) ? 8'd255 : 8'd0;
                    s_axis_tlast  = (index == NPIX - 1);
                    do @(posedge aclk); while (!s_axis_tready);
                    @(negedge aclk);
                end
            end

            s_axis_tvalid = 1'b0;
            s_axis_tdata  = 8'd0;
            s_axis_tlast  = 1'b0;
        end
    endtask

    initial begin : test_sequence
        integer frame;
        integer timeout_cycles;
        integer total_mismatches;

        load_vectors();
        for (frame = 0; frame < FRAMES; frame = frame + 1) begin
            received[frame]  = 0;
            mismatches[frame] = 0;
            tlast_bad[frame] = 0;
        end

        aresetn       = 1'b0;
        s_axis_tvalid = 1'b0;
        s_axis_tdata  = 8'd0;
        s_axis_tlast  = 1'b0;
        m_axis_tready = 1'b0;
        threshold     = 16'd80;
        enable        = 1'b1;
        repeat (6) @(posedge aclk);
        @(negedge aclk);
        aresetn = 1'b1;

        fork
            send_two_frames();
            begin
                timeout_cycles = 0;
                while (output_frame < FRAMES && timeout_cycles < 700000) begin
                    @(posedge aclk);
                    timeout_cycles = timeout_cycles + 1;
                end
                if (output_frame < FRAMES) begin
                    $display("FAIL: timeout, completed frames=%0d", output_frame);
                    $fatal(1);
                end
            end
        join

        repeat (4) @(posedge aclk);
        total_mismatches = mismatches[0] + mismatches[1];
        for (frame = 0; frame < FRAMES; frame = frame + 1) begin
            $display("Frame %0d: grid counts: %0d, mismatches: %0d",
                     frame + 1, received[frame], mismatches[frame]);
        end

        if (received[0] == GRID_COUNT && received[1] == GRID_COUNT
            && total_mismatches == 0
            && tlast_bad[0] == 0 && tlast_bad[1] == 0
            && handshake_bad == 0) begin
            $display("grid counts: 48, mismatches: 0, PASS");
        end
        else begin
            $display("FAIL: total_mismatches=%0d tlast_bad=%0d/%0d handshake_bad=%0d",
                     total_mismatches, tlast_bad[0], tlast_bad[1], handshake_bad);
            $fatal(1);
        end
        $finish;
    end

endmodule
