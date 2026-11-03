`timescale 1ns / 1ps

module tb_sobel_axis;

    localparam integer WIDTH  = 640;
    localparam integer HEIGHT = 480;
    localparam integer NPIX   = WIDTH * HEIGHT;
    localparam integer FRAMES = 2;

    reg         aclk;
    reg         aresetn;
    reg   [7:0] s_axis_tdata;
    reg         s_axis_tvalid;
    wire        s_axis_tready;
    reg         s_axis_tlast;
    wire  [7:0] m_axis_tdata;
    wire        m_axis_tvalid;
    reg         m_axis_tready;
    wire        m_axis_tlast;

    byte unsigned input_mem [0:NPIX-1];
    byte unsigned edge_mem  [0:NPIX-1];

    integer frame_pixels [0:FRAMES-1];
    integer mismatches   [0:FRAMES-1];
    integer border_bad   [0:FRAMES-1];
    integer tlast_bad    [0:FRAMES-1];
    integer output_frame;
    integer output_index;
    integer ready_cycle;
    integer handshake_bad;
    reg   [7:0] stalled_data;
    reg         stalled_last;
    reg         was_stalled;

    sobel_axis dut (
        .aclk          (aclk),
        .aresetn       (aresetn),
        .s_axis_tdata  (s_axis_tdata),
        .s_axis_tvalid (s_axis_tvalid),
        .s_axis_tready (s_axis_tready),
        .s_axis_tlast  (s_axis_tlast),
        .m_axis_tdata  (m_axis_tdata),
        .m_axis_tvalid (m_axis_tvalid),
        .m_axis_tready (m_axis_tready),
        .m_axis_tlast  (m_axis_tlast)
    );

    initial begin
        aclk = 1'b0;
        forever #5 aclk = ~aclk;
    end

    // 周期性制造输出反压，验证 valid/data/last 在 ready=0 时保持稳定
    always @(negedge aclk) begin
        if (!aresetn) begin
            ready_cycle   <= 0;
            m_axis_tready <= 1'b0;
        end
        else begin
            ready_cycle   <= ready_cycle + 1;
            m_axis_tready <= ((ready_cycle % 23) != 0)
                          && ((ready_cycle % 41) != 0);
        end
    end

    // 输出逐像素检查
    always @(posedge aclk) begin
        integer x;
        integer y;
        reg   [7:0] expected_binary;

        if (!aresetn) begin
            output_frame <= 0;
            output_index <= 0;
            handshake_bad <= 0;
            was_stalled <= 1'b0;
            stalled_data <= 8'd0;
            stalled_last <= 1'b0;
        end
        else begin
            if (was_stalled) begin
                if (!m_axis_tvalid || m_axis_tdata !== stalled_data
                    || m_axis_tlast !== stalled_last)
                    handshake_bad <= handshake_bad + 1;
            end

            was_stalled <= m_axis_tvalid && !m_axis_tready;
            if (m_axis_tvalid && !m_axis_tready) begin
                stalled_data <= m_axis_tdata;
                stalled_last <= m_axis_tlast;
            end

            if (m_axis_tvalid && m_axis_tready) begin
                x = output_index % WIDTH;
                y = output_index / WIDTH;
                expected_binary = (edge_mem[output_index] >= 8'd80) ? 8'd255 : 8'd0;

                frame_pixels[output_frame] <= frame_pixels[output_frame] + 1;
                if (m_axis_tdata !== expected_binary) begin
                    if (mismatches[output_frame] < 10)
                        $display("Frame %0d mismatch x=%0d y=%0d got=%0d expected=%0d",
                                 output_frame + 1, x, y, m_axis_tdata, expected_binary);
                    mismatches[output_frame] <= mismatches[output_frame] + 1;
                end

                if ((x == 0 || x == WIDTH-1 || y == 0 || y == HEIGHT-1)
                    && m_axis_tdata !== 8'd0)
                    border_bad[output_frame] <= border_bad[output_frame] + 1;

                if (m_axis_tlast !== (output_index == NPIX-1))
                    tlast_bad[output_frame] <= tlast_bad[output_frame] + 1;

                if (output_index == NPIX-1) begin
                    output_index <= 0;
                    output_frame <= output_frame + 1;
                end
                else begin
                    output_index <= output_index + 1;
                end
            end
        end
    end

    task automatic load_vector;
        string input_path;
        string edge_path;
        integer fd;
        integer count;
        begin
            if (!$value$plusargs("IN=%s", input_path)) begin
                input_path = "data/hdl_vectors/single_target_640x480_input.bin";
            end
            if (!$value$plusargs("EXP=%s", edge_path)) begin
                edge_path = "data/hdl_vectors/single_target_640x480_expected.bin";
            end

            fd = $fopen(input_path, "rb");
            if (fd == 0) begin
                $display("ERROR: cannot open %s; use +IN=<absolute_path> or sim/run_rtl_sim.tcl", input_path);
                $fatal(1);
            end
            count = $fread(input_mem, fd);
            $fclose(fd);
            if (count != NPIX) begin
                $display("ERROR: input bytes=%0d expected=%0d", count, NPIX);
                $fatal(1);
            end

            fd = $fopen(edge_path, "rb");
            if (fd == 0) begin
                $display("ERROR: cannot open %s; use +EXP=<absolute_path> or sim/run_rtl_sim.tcl", edge_path);
                $fatal(1);
            end
            count = $fread(edge_mem, fd);
            $fclose(fd);
            if (count != NPIX) begin
                $display("ERROR: expected bytes=%0d expected=%0d", count, NPIX);
                $fatal(1);
            end
        end
    endtask

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
                    s_axis_tdata  = input_mem[index];
                    s_axis_tlast  = (index == NPIX-1);
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

        load_vector();
        for (frame = 0; frame < FRAMES; frame = frame + 1) begin
            frame_pixels[frame] = 0;
            mismatches[frame]   = 0;
            border_bad[frame]   = 0;
            tlast_bad[frame]    = 0;
        end

        aresetn       = 1'b0;
        s_axis_tvalid = 1'b0;
        s_axis_tdata  = 8'd0;
        s_axis_tlast  = 1'b0;
        m_axis_tready = 1'b0;
        repeat (6) @(posedge aclk);
        @(negedge aclk);
        aresetn = 1'b1;

        fork
            send_two_frames();
            begin
                timeout_cycles = 0;
                while (output_frame < FRAMES && timeout_cycles < 900000) begin
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
        for (frame = 0; frame < FRAMES; frame = frame + 1) begin
            $display("Frame %0d: output pixels: %0d, mismatches: %0d, border_nonzero: %0d",
                     frame + 1, frame_pixels[frame], mismatches[frame], border_bad[frame]);
        end

        if (frame_pixels[0] == NPIX && frame_pixels[1] == NPIX
            && mismatches[0] == 0 && mismatches[1] == 0
            && border_bad[0] == 0 && border_bad[1] == 0
            && tlast_bad[0] == 0 && tlast_bad[1] == 0
            && handshake_bad == 0) begin
            $display("PASS");
        end
        else begin
            $display("FAIL: tlast_bad=%0d/%0d handshake_bad=%0d",
                     tlast_bad[0], tlast_bad[1], handshake_bad);
            $fatal(1);
        end
        $finish;
    end

endmodule
