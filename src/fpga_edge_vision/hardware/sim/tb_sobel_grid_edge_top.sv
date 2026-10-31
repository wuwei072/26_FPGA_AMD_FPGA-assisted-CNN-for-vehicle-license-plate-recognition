`timescale 1ns / 1ps

module tb_sobel_grid_edge_top;

    localparam integer WIDTH        = 640;
    localparam integer HEIGHT       = 480;
    localparam integer NPIX         = WIDTH * HEIGHT;
    localparam integer FRAMES       = 2;
    localparam integer OUTPUT_WORDS = 6;
    localparam integer TIMEOUT_CLKS = 1200000;

    reg   [15:0] EXPECTED_OUTPUT [0:OUTPUT_WORDS-1];

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

    wire  [7:0]  edge_m_axis_tdata;
    wire         edge_m_axis_tvalid;
    reg          edge_m_axis_tready;
    wire         edge_m_axis_tlast;

    byte unsigned input_mem [0:NPIX-1];
    byte unsigned expected_edge_mem [0:NPIX-1];
    reg   [15:0] observed [0:FRAMES-1][0:OUTPUT_WORDS-1];

    integer roi_received [0:FRAMES-1];
    integer roi_mismatches [0:FRAMES-1];
    integer roi_tlast_bad [0:FRAMES-1];
    integer edge_received [0:FRAMES-1];
    integer edge_mismatches [0:FRAMES-1];
    integer edge_tlast_bad [0:FRAMES-1];

    integer roi_frame;
    integer roi_index;
    integer edge_frame;
    integer edge_index;
    integer roi_ready_cycle;
    integer edge_ready_cycle;
    integer roi_handshake_bad;
    integer edge_handshake_bad;

    reg   [15:0] stalled_roi_data;
    reg          stalled_roi_last;
    reg          was_roi_stalled;
    reg   [7:0]  stalled_edge_data;
    reg          stalled_edge_last;
    reg          was_edge_stalled;

    sobel_grid_edge_top dut (
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
        .active_threshold       (16'd768)
    );

    initial begin
        aclk = 1'b0;
        // 50 MHz，对应新Block Design的20 ns周期。
        forever #10 aclk = ~aclk;
    end

    // ROI每5拍反压1拍，边缘图每7拍反压1拍，验证两路可独立停顿。
    always @(negedge aclk) begin
        if (!aresetn) begin
            roi_ready_cycle   <= 0;
            edge_ready_cycle  <= 0;
            m_axis_tready     <= 1'b0;
            edge_m_axis_tready <= 1'b0;
        end
        else begin
            roi_ready_cycle    <= roi_ready_cycle + 1;
            edge_ready_cycle   <= edge_ready_cycle + 1;
            m_axis_tready      <= ((roi_ready_cycle % 5) != 0);
            edge_m_axis_tready <= ((edge_ready_cycle % 7) != 0);
        end
    end

    // ROI接收、内容检查和反压稳定性检查。
    always @(posedge aclk) begin
        if (!aresetn) begin
            roi_frame        <= 0;
            roi_index        <= 0;
            was_roi_stalled  <= 1'b0;
            stalled_roi_data <= 16'd0;
            stalled_roi_last <= 1'b0;
        end
        else begin
            if (was_roi_stalled
                && (m_axis_tvalid !== 1'b1
                    || m_axis_tdata !== stalled_roi_data
                    || m_axis_tlast !== stalled_roi_last)) begin
                $display("FAIL: ROI AXIS changed while stalled");
                roi_handshake_bad <= roi_handshake_bad + 1;
            end

            was_roi_stalled <= m_axis_tvalid && !m_axis_tready;
            if (m_axis_tvalid && !m_axis_tready) begin
                stalled_roi_data <= m_axis_tdata;
                stalled_roi_last <= m_axis_tlast;
            end

            if (m_axis_tvalid && m_axis_tready) begin
                if (roi_frame >= FRAMES) begin
                    $fatal(1, "FAIL: unexpected extra ROI word");
                end

                observed[roi_frame][roi_index] <= m_axis_tdata;
                roi_received[roi_frame] <= roi_received[roi_frame] + 1;

                if (m_axis_tdata !== EXPECTED_OUTPUT[roi_index]) begin
                    roi_mismatches[roi_frame] <= roi_mismatches[roi_frame] + 1;
                end
                if (m_axis_tlast !== (roi_index == OUTPUT_WORDS - 1)) begin
                    roi_tlast_bad[roi_frame] <= roi_tlast_bad[roi_frame] + 1;
                end

                if (roi_index == OUTPUT_WORDS - 1) begin
                    roi_index <= 0;
                    roi_frame <= roi_frame + 1;
                end
                else begin
                    roi_index <= roi_index + 1;
                end
            end
        end
    end

    // 真实边缘流逐像素Golden比较，并检查反压时保持稳定。
    always @(posedge aclk) begin
        if (!aresetn) begin
            edge_frame        <= 0;
            edge_index        <= 0;
            was_edge_stalled  <= 1'b0;
            stalled_edge_data <= 8'd0;
            stalled_edge_last <= 1'b0;
        end
        else begin
            if (was_edge_stalled
                && (edge_m_axis_tvalid !== 1'b1
                    || edge_m_axis_tdata !== stalled_edge_data
                    || edge_m_axis_tlast !== stalled_edge_last)) begin
                $display("FAIL: edge AXIS changed while stalled");
                edge_handshake_bad <= edge_handshake_bad + 1;
            end

            was_edge_stalled <= edge_m_axis_tvalid && !edge_m_axis_tready;
            if (edge_m_axis_tvalid && !edge_m_axis_tready) begin
                stalled_edge_data <= edge_m_axis_tdata;
                stalled_edge_last <= edge_m_axis_tlast;
            end

            if (edge_m_axis_tvalid && edge_m_axis_tready) begin
                if (edge_frame >= FRAMES) begin
                    $fatal(1, "FAIL: unexpected extra edge pixel");
                end

                edge_received[edge_frame] <= edge_received[edge_frame] + 1;
                if (edge_m_axis_tdata !==
    ((expected_edge_mem[edge_index] >= 8'd80) ? 8'd255 : 8'd0)) begin

    if (edge_mismatches[edge_frame] < 8) begin
        $display(
            "Frame %0d edge mismatch @%0d: got=%0d expected_binary=%0d raw_mag=%0d",
            edge_frame + 1,
            edge_index,
            edge_m_axis_tdata,
            (expected_edge_mem[edge_index] >= 8'd80) ? 8'd255 : 8'd0,
            expected_edge_mem[edge_index]
        );
    end

    edge_mismatches[edge_frame]
        <= edge_mismatches[edge_frame] + 1;
end

                if (edge_m_axis_tlast !== (edge_index == NPIX - 1)) begin
                    edge_tlast_bad[edge_frame] <= edge_tlast_bad[edge_frame] + 1;
                end

                if (edge_index == NPIX - 1) begin
                    edge_index <= 0;
                    edge_frame <= edge_frame + 1;
                end
                else begin
                    edge_index <= edge_index + 1;
                end
            end
        end
    end

    task automatic load_binary_exact(
        input string plusarg_name,
        input string default_name,
        input bit is_input
    );
        string path;
        integer fd;
        integer byte_count;
        integer extra_byte;
        begin
            fd = 0;
            if (!$value$plusargs(plusarg_name, path)) begin
                path = {"../../../../../../sim/vectors/", default_name};
            end
            fd = $fopen(path, "rb");
            if (fd == 0) begin
                path = {"hardware/sim/vectors/", default_name};
                fd = $fopen(path, "rb");
            end
            if (fd == 0) begin
                $fatal(1, "ERROR: cannot open %s", path);
            end

            if (is_input) begin
                byte_count = $fread(input_mem, fd);
            end
            else begin
                byte_count = $fread(expected_edge_mem, fd);
            end
            extra_byte = $fgetc(fd);
            $fclose(fd);
            if (byte_count != NPIX || extra_byte != -1) begin
                $fatal(1, "ERROR: %s must contain exactly %0d bytes; got=%0d extra=%0d",
                       path, NPIX, byte_count, extra_byte);
            end
            $display("INFO: loaded %s", path);
        end
    endtask

task automatic load_expected_output;
    string expected_text;
    integer parsed;
    integer value0;
    integer value1;
    integer value2;
    integer value3;
    integer value4;
    integer value5;
    begin
        // single_target默认期望值
        EXPECTED_OUTPUT[0] = 16'd160;
        EXPECTED_OUTPUT[1] = 16'd160;
        EXPECTED_OUTPUT[2] = 16'd160;
        EXPECTED_OUTPUT[3] = 16'd160;
        EXPECTED_OUTPUT[4] = 16'd4;
        EXPECTED_OUTPUT[5] = 16'd9167;

        if ($value$plusargs("EXPECTED=%s", expected_text)) begin
            parsed = $sscanf(
                expected_text,
                "%d,%d,%d,%d,%d,%d",
                value0, value1, value2,
                value3, value4, value5
            );

            if (parsed != 6) begin
                $fatal(
                    1,
                    "ERROR: +EXPECTED needs 6 comma-separated integers; got=%s",
                    expected_text
                );
            end
            if (value0 < 0 || value0 > 65535
                || value1 < 0 || value1 > 65535
                || value2 < 0 || value2 > 65535
                || value3 < 0 || value3 > 65535
                || value4 < 0 || value4 > 65535
                || value5 < 0 || value5 > 65535) begin
                $fatal(1, "ERROR: +EXPECTED fields must be 0..65535");
            end

            EXPECTED_OUTPUT[0] = value0;
            EXPECTED_OUTPUT[1] = value1;
            EXPECTED_OUTPUT[2] = value2;
            EXPECTED_OUTPUT[3] = value3;
            EXPECTED_OUTPUT[4] = value4;
            EXPECTED_OUTPUT[5] = value5;
        end
    end
endtask

    task automatic send_two_frames;
        integer frame;
        integer pixel;
        begin
            s_axis_tvalid = 1'b0;
            s_axis_tdata  = 8'd0;
            s_axis_tlast  = 1'b0;
            @(negedge aclk);
            for (frame = 0; frame < FRAMES; frame = frame + 1) begin
                for (pixel = 0; pixel < NPIX; pixel = pixel + 1) begin
                    s_axis_tvalid = 1'b1;
                    s_axis_tdata  = input_mem[pixel];
                    s_axis_tlast  = (pixel == NPIX - 1);
                    do @(posedge aclk); while (s_axis_tready !== 1'b1);
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
        integer field;
        integer timeout_cycles;
        integer total_roi_mismatch;
        integer total_edge_mismatch;
        integer total_tlast_bad;

        load_expected_output();
        load_binary_exact("IN=%s", "single_target_640x480_input.bin", 1'b1);
        load_binary_exact("EDGE=%s", "single_target_640x480_expected.bin", 1'b0);

        roi_handshake_bad  = 0;
        edge_handshake_bad = 0;
        for (frame = 0; frame < FRAMES; frame = frame + 1) begin
            roi_received[frame]    = 0;
            roi_mismatches[frame]  = 0;
            roi_tlast_bad[frame]   = 0;
            edge_received[frame]   = 0;
            edge_mismatches[frame] = 0;
            edge_tlast_bad[frame]  = 0;
            for (field = 0; field < OUTPUT_WORDS; field = field + 1) begin
                observed[frame][field] = 16'd0;
            end
        end

        aresetn           = 1'b0;
        s_axis_tvalid     = 1'b0;
        s_axis_tdata      = 8'd0;
        s_axis_tlast      = 1'b0;
        m_axis_tready     = 1'b0;
        edge_m_axis_tready = 1'b0;
        repeat (6) @(posedge aclk);
        @(negedge aclk);
        aresetn = 1'b1;

        fork
            send_two_frames();
            begin
                timeout_cycles = 0;
                while ((roi_frame < FRAMES || edge_frame < FRAMES)
                       && timeout_cycles < TIMEOUT_CLKS) begin
                    @(posedge aclk);
                    timeout_cycles = timeout_cycles + 1;
                end
                if (roi_frame < FRAMES || edge_frame < FRAMES) begin
                    $fatal(1, "FAIL: timeout roi_frames=%0d edge_frames=%0d",
                           roi_frame, edge_frame);
                end
            end
        join

        repeat (8) @(posedge aclk);
        total_roi_mismatch  = roi_mismatches[0] + roi_mismatches[1];
        total_edge_mismatch = edge_mismatches[0] + edge_mismatches[1];
        total_tlast_bad = roi_tlast_bad[0] + roi_tlast_bad[1]
                        + edge_tlast_bad[0] + edge_tlast_bad[1];

        for (frame = 0; frame < FRAMES; frame = frame + 1) begin
            $display("Frame %0d: edge_pixels=%0d edge_mismatches=%0d ROI=(%0d,%0d,%0d,%0d) best=%0d reduction=%0d.%02d%% roi_mismatches=%0d",
                     frame + 1, edge_received[frame], edge_mismatches[frame],
                     observed[frame][0], observed[frame][1],
                     observed[frame][2], observed[frame][3], observed[frame][4],
                     observed[frame][5] / 100, observed[frame][5] % 100,
                     roi_mismatches[frame]);
        end

        if (roi_received[0] == OUTPUT_WORDS
            && roi_received[1] == OUTPUT_WORDS
            && edge_received[0] == NPIX
            && edge_received[1] == NPIX
            && total_roi_mismatch == 0
            && total_edge_mismatch == 0
            && total_tlast_bad == 0
            && roi_handshake_bad == 0
            && edge_handshake_bad == 0) begin
            $display("PASS");
        end
        else begin
            $fatal(1, "FAIL: roi_mismatch=%0d edge_mismatch=%0d tlast_bad=%0d roi_handshake_bad=%0d edge_handshake_bad=%0d",
                   total_roi_mismatch, total_edge_mismatch,
                   total_tlast_bad, roi_handshake_bad, edge_handshake_bad);
        end
        $finish;
    end

endmodule

