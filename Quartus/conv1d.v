/*
 * Module: conv1d
 * Description: 1D Convolution engine using Q16.16 fixed-point arithmetic.
 * Optimized for FPGA/HPS interaction on the DE1-SoC.
 */

module conv1d #(
    parameter DATA_WIDTH     = 32,
    parameter XN_LENGTH      = 128, // Input signal length
    parameter HN_LENGTH      = 128, // Filter impulse response length
    parameter YN_LENGTH      = 255, // Result length (L+M-1)
    parameter XN_ADDR_N_BITS = 7,
    parameter HN_ADDR_N_BITS = 7,
    parameter YN_ADDR_N_BITS = 8
)(
    input  wire                        clk,
    input  wire                        reset_n,
    input  wire                        start,    // Pulse from HPS to begin execution
    output reg                         done,     // Signal to HPS that Y[n] is complete

    // --- SRAM Interface for Input x[n] ---
    input  wire [DATA_WIDTH-1:0]       xn_sram_readdata,
    output wire [XN_ADDR_N_BITS-1:0]   xn_sram_address,
    output wire                        xn_sram_chipselect,
    output wire                        xn_sram_clken,
    output wire                        xn_sram_write,

    // --- SRAM Interface for Impulse Response h[n] ---
    input  wire [DATA_WIDTH-1:0]       hn_sram_readdata,
    output wire [HN_ADDR_N_BITS-1:0]   hn_sram_address,
    output wire                        hn_sram_chipselect,
    output wire                        hn_sram_clken,
    output wire                        hn_sram_write,

    // --- SRAM Interface for Output y[n] ---
    output wire [YN_ADDR_N_BITS-1:0]   yn_sram_address,
    output wire [DATA_WIDTH-1:0]       yn_sram_wdata,
    output wire                        yn_sram_chipselect,
    output wire                        yn_sram_clken,
    output wire                        yn_sram_write
);

    // --- FSM State Definitions ---
    localparam [3:0] IDLE       = 4'd0; // Wait for start pulse
    localparam [3:0] PREPARE_K  = 4'd1; // Set k_start and clear accumulator
    localparam [3:0] COMPUTING  = 4'd2; // Bounds checking for current k
    localparam [3:0] READ_MEM   = 4'd3; // Trigger multi-cycle read from SRAM
    localparam [3:0] WAIT_READ  = 4'd4; // Wait for SRAM controllers to finish
    localparam [3:0] ACCUMULATE = 4'd5; // Multiply-Accumulate (MAC) operation
    localparam [3:0] WRITE_MEM  = 4'd6; // Trigger multi-cycle write to SRAM
    localparam [3:0] WAIT_WRITE = 4'd7; // Wait for write completion
    localparam [3:0] DONE       = 4'd8; // Signal task completion

    reg [3:0] state;
    reg start_d;
    wire start_conv;

    // Edge detector for 'start' signal to ensure it only runs once per press
    always @(posedge clk or negedge reset_n) begin
        if (!reset_n) start_d <= 1'b0;
        else          start_d <= start;
    end
    assign start_conv = start & ~start_d;

    reg [YN_ADDR_N_BITS-1:0]  n; // Outer loop index (output samples)
    reg [XN_ADDR_N_BITS:0]    k; // Inner loop index (summation)

    // --- Dynamic Limit Logic ---
    // k_start = max(0, n - M + 1) -> Prevents negative indices for h[n-k]
    wire [XN_ADDR_N_BITS:0] k_start_val = (n < HN_LENGTH) ? 0 : (n - HN_LENGTH + 1);
    // k_end = min(n, L - 1) -> Prevents index exceeding signal length
    wire [XN_ADDR_N_BITS:0] k_end_val   = (n < XN_LENGTH) ? n : (XN_LENGTH - 1);
    
    // Calculate h[n-k] index with safe bit expansion
    wire signed [YN_ADDR_N_BITS:0] hn_idx = $signed({1'b0, n}) - $signed({1'b0, k[XN_ADDR_N_BITS-1:0]});

    // Control and Data signals for sub-modules
    reg                          xn_start_read;
    reg  [XN_ADDR_N_BITS-1:0]    xn_data_addr;
    wire [DATA_WIDTH-1:0]        xn_data_out;
    wire                         xn_read_done;
    reg                          xn_done_latch; // Stores completion state if one RAM is faster

    reg                          hn_start_read;
    reg  [HN_ADDR_N_BITS-1:0]    hn_data_addr;
    wire [DATA_WIDTH-1:0]        hn_data_out;
    wire                         hn_read_done;
    reg                          hn_done_latch;

    reg                          yn_start_write;
    reg  [YN_ADDR_N_BITS-1:0]    yn_data_in_addr;
    reg  [DATA_WIDTH-1:0]        yn_data_in;
    wire                         yn_write_done;

    reg signed [DATA_WIDTH-1:0] accumulator; // Running sum for current y[n]
    reg signed [DATA_WIDTH-1:0] xn_latched;   // Sample from x[k]
    reg signed [DATA_WIDTH-1:0] hn_latched;   // Sample from h[n-k]

    // --- Q16.16 Multiplication ---
    // 32x32 bit multiply results in a 64-bit product.
    // We shift by 16 bits to maintain the Q16.16 fractional alignment.
    wire signed [2*DATA_WIDTH-1:0] mult_result = xn_latched * hn_latched;
    wire signed [DATA_WIDTH-1:0]   mult_fixed  = mult_result[DATA_WIDTH+16-1:16];

    // --- Sub-module Instances (Memory Controllers) ---
    memory_read_controller #(.DATA_WIDTH(DATA_WIDTH), .MEM_ADDRESS_N_BITS(XN_ADDR_N_BITS)) u_xn_read_ctrl (
        .clk(clk), .reset_n(reset_n), .start_read(xn_start_read), .data_addr(xn_data_addr),
        .data_out(xn_data_out), .read_done(xn_read_done), .sram_readdata(xn_sram_readdata),
        .mem_address(xn_sram_address), .mem_write(xn_sram_write), .clken(xn_sram_clken), .chipselect(xn_sram_chipselect)
    );

    memory_read_controller #(.DATA_WIDTH(DATA_WIDTH), .MEM_ADDRESS_N_BITS(HN_ADDR_N_BITS)) u_hn_read_ctrl (
        .clk(clk), .reset_n(reset_n), .start_read(hn_start_read), .data_addr(hn_data_addr),
        .data_out(hn_data_out), .read_done(hn_read_done), .sram_readdata(hn_sram_readdata),
        .mem_address(hn_sram_address), .mem_write(hn_sram_write), .clken(hn_sram_clken), .chipselect(hn_sram_chipselect)
    );

    memory_write_controller #(.DATA_WIDTH(DATA_WIDTH), .MEM_ADDRESS_N_BITS(YN_ADDR_N_BITS)) u_yn_write_ctrl (
        .clk(clk), .reset_n(reset_n), .start_write(yn_start_write), .data_in_addr(yn_data_in_addr),
        .data_in(yn_data_in), .write_done(yn_write_done), .mem_address(yn_sram_address), .mem_wdata(yn_sram_wdata),
        .mem_write(yn_sram_write), .clken(yn_sram_clken), .chipselect(yn_sram_chipselect)
    );

    // --- Main Control Logic ---
    always @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            state <= IDLE;
            n <= 0; k <= 0; accumulator <= 0;
            xn_start_read <= 0; hn_start_read <= 0; yn_start_write <= 0;
            done <= 0; xn_done_latch <= 0; hn_done_latch <= 0;
        end else begin
            // Default: start pulses are only 1 clock cycle long
            xn_start_read  <= 1'b0;
            hn_start_read  <= 1'b0;
            yn_start_write <= 1'b0;

            case (state)
                IDLE: begin
                    if (start_conv) begin
                        n <= 0;
                        done <= 1'b0;
                        state <= PREPARE_K;
                    end
                end

                PREPARE_K: begin
                    if (n < YN_LENGTH) begin
                        k <= k_start_val;
                        accumulator <= 0; // Clear sum before starting inner loop
                        state <= COMPUTING;
                    end else begin
                        state <= DONE; // All n samples processed
                    end
                end

                COMPUTING: begin
                    if (k <= k_end_val) begin
                        // Map the calculated indices to the memory request registers
                        xn_data_addr <= k[XN_ADDR_N_BITS-1:0];
                        hn_data_addr <= hn_idx[HN_ADDR_N_BITS-1:0];
                        state <= READ_MEM;
                    end else begin
                        // Inner loop finished, proceed to save result
                        state <= WRITE_MEM;
                    end
                end

                READ_MEM: begin
                    xn_start_read <= 1'b1;
                    hn_start_read <= 1'b1;
                    xn_done_latch <= 1'b0;
                    hn_done_latch <= 1'b0;
                    state <= WAIT_READ;
                end

                WAIT_READ: begin
                    // Sync pulses from two independent memory controllers
                    if (xn_read_done) xn_done_latch <= 1'b1;
                    if (hn_read_done) hn_done_latch <= 1'b1;

                    // Transition only when both data points are ready in data_out
                    if ((xn_read_done || xn_done_latch) && (hn_read_done || hn_done_latch)) begin
                        xn_latched <= $signed(xn_data_out);
                        hn_latched <= $signed(hn_data_out);
                        state <= ACCUMULATE;
                    end
                end

                ACCUMULATE: begin
                    // Perform the summation part of the convolution formula
                    accumulator <= accumulator + mult_fixed;
                    k <= k + 1'b1; // Advance the inner summation index
                    state <= COMPUTING;
                end

                WRITE_MEM: begin
                    yn_data_in_addr <= n;
                    yn_data_in <= accumulator; // Load the final sum into write register
                    yn_start_write <= 1'b1;
                    state <= WAIT_WRITE;
                end

                WAIT_WRITE: begin
                    // Wait until the SRAM controller confirms the write operation
                    if (yn_write_done) begin
                        n <= n + 1'b1; // Move to the next output sample
                        state <= PREPARE_K;
                    end
                end

                DONE: begin
                    done <= 1'b1; // Inform HPS the entire buffer is ready
                    state <= IDLE;
                end
                
                default: state <= IDLE;
            endcase
        end
    end
endmodule