// ============================================================================
// morphe_fft_wrapper.v (REVISED & COMMENTED)
//
// Wrapper orchestrating communication between HPS and Intel FFT IP Core.
// Uses Avalon-ST handshakes to ensure no samples are dropped during 
// the feed or receive phases.
// ============================================================================

module fft_wrapper #(
    parameter FFT_N           = 1024,
    parameter SRAM_DATA_WIDTH = 32,   // 32-bit on-chip memory support
    parameter FFT_DATA_WIDTH  = 24,   // Intel FFT IP Core bit-width
    parameter ADDR_BITS       = 10,   // log2(FFT_N)
    parameter EXP_WIDTH       = 6
)(
    input wire clk,
    input wire reset_n,

    // --- HPS Control Interface (PIOs) ---
    input  wire                       start,          
    input  wire                       inverse,        
    output reg                        done,           
    output reg  [EXP_WIDTH-1:0]       fft_exponent,   

    // --- SRAM Interfaces (Real/Imag Input and Output) ---
    // Port B connections to the four SRAM blocks
    output wire [ADDR_BITS-1:0]       in_real_mem_address,
    output wire                       in_real_mem_write,
    output wire                       in_real_clken,
    output wire                       in_real_chipselect,
    input  wire [SRAM_DATA_WIDTH-1:0] in_real_sram_readdata,

    output wire [ADDR_BITS-1:0]       in_imag_mem_address,
    output wire                       in_imag_mem_write,
    output wire                       in_imag_clken,
    output wire                       in_imag_chipselect,
    input  wire [SRAM_DATA_WIDTH-1:0] in_imag_sram_readdata,

    output wire [ADDR_BITS-1:0]       out_real_mem_address,
    output wire [SRAM_DATA_WIDTH-1:0] out_real_mem_wdata,
    output wire                       out_real_mem_write,
    output wire                       out_real_clken,
    output wire                       out_real_chipselect,

    output wire [ADDR_BITS-1:0]       out_imag_mem_address,
    output wire [SRAM_DATA_WIDTH-1:0] out_imag_mem_wdata,
    output wire                       out_imag_mem_write,
    output wire                       out_imag_clken,
    output wire                       out_imag_chipselect,

    output wire [3:0]                 debug_state
);

    // --- FSM State Definitions ---
    localparam S_IDLE        = 4'd0; // Wait for HPS start pulse
    localparam S_READ_START  = 4'd1; // Request sample from Input SRAM
    localparam S_READ_WAIT   = 4'd2; // Wait for Input SRAM Controller latency
    localparam S_FEED_FFT    = 4'd3; // Handshake: Send sample to FFT IP Core
    localparam S_RECV_WAIT   = 4'd4; // Handshake: Wait for result from FFT IP Core
    localparam S_WRITE_START = 4'd5; // Request write to Output SRAM
    localparam S_WRITE_WAIT  = 4'd6; // Wait for Output SRAM Controller latency
    localparam S_COMPLETE    = 4'd7; // Signal HPS and wait for start to go LOW

    reg [3:0] state;
    assign debug_state = state;

    reg [ADDR_BITS-1:0] feed_addr; // Counter for input samples
    reg [ADDR_BITS-1:0] recv_addr; // Counter for output bins

    // --- Pulse Detector for HPS Start Signal ---
    reg start_prev;
    wire start_rising = start & ~start_prev;
    always @(posedge clk or negedge reset_n) begin
        if (!reset_n) start_prev <= 1'b0;
        else          start_prev <= start;
    end

    reg inverse_reg; // Latch inverse bit at start

    // --- Memory Controller Sub-signals ---
    reg                       rd_start;
    reg  [ADDR_BITS-1:0]      rd_addr;
    wire [SRAM_DATA_WIDTH-1:0] rd_real_data_out, rd_imag_data_out;
    wire                      rd_real_done, rd_imag_done;
    wire rd_done = rd_real_done & rd_imag_done;

    reg                       wr_start;
    reg  [ADDR_BITS-1:0]      wr_addr;
    reg  [SRAM_DATA_WIDTH-1:0] wr_real_data, wr_imag_data;
    wire                      wr_real_done, wr_imag_done;
    wire wr_done = wr_real_done & wr_imag_done;

    // --- Avalon-ST Signals for FFT IP Core ---
    reg                            sink_valid;
    wire                           sink_ready;
    reg  [1:0]                     sink_error;
    reg                            sink_sop;
    reg                            sink_eop;
    reg  [FFT_DATA_WIDTH-1:0]      sink_real, sink_imag;

    wire                           source_valid;
    reg                            source_ready;
    wire [1:0]                     source_error;
    wire                           source_sop, source_eop;
    wire [FFT_DATA_WIDTH-1:0]      source_real, source_imag; 
    wire [EXP_WIDTH-1:0]           source_exp;

    reg [SRAM_DATA_WIDTH-1:0]      capt_real, capt_imag;

    // --- Main FSM Logic ---
    always @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            state        <= S_IDLE;
            done         <= 1'b0;
            fft_exponent <= 0;
            feed_addr <= 0; recv_addr <= 0;
            sink_valid <= 0; sink_error <= 0; sink_sop <= 0; sink_eop <= 0;
            source_ready <= 0; // START AT ZERO to avoid lost samples!
            rd_start <= 0; wr_start <= 0;
        end
        else begin
            rd_start   <= 1'b0;
            wr_start   <= 1'b0;
            
            case (state)
                S_IDLE: begin
                    done         <= 1'b0;
                    source_ready <= 1'b0; // Ensure FFT output is blocked
                    sink_valid   <= 1'b0;
                    if (start_rising) begin
                        feed_addr    <= 0;
                        recv_addr    <= 0;
                        inverse_reg  <= inverse;
                        state        <= S_READ_START;
                    end
                end

                S_READ_START: begin
                    rd_addr    <= feed_addr;
                    rd_start   <= 1'b1;
                    sink_valid <= 1'b0;
                    state      <= S_READ_WAIT;
                end

                S_READ_WAIT: begin
                    if (rd_done) begin
                        // Latch data from SRAM and prepare Avalon packet signals
                        sink_real  <= rd_real_data_out[FFT_DATA_WIDTH-1:0];
                        sink_imag  <= rd_imag_data_out[FFT_DATA_WIDTH-1:0];
                        sink_sop   <= (feed_addr == 0);
                        sink_eop   <= (feed_addr == FFT_N - 1);
                        sink_valid <= 1'b1; // Data is now valid for the FFT Core
                        state      <= S_FEED_FFT;
                    end
                end

                S_FEED_FFT: begin
                    // Wait for the FFT Core to acknowledge the sample (sink_ready)
                    if (sink_ready) begin
                        sink_valid <= 1'b0; 
                        if (feed_addr == FFT_N - 1) begin
                            state <= S_RECV_WAIT;
                        end
                        else begin
                            feed_addr  <= feed_addr + 1'b1;
                            state      <= S_READ_START;
                        end
                    end
                end
                
                S_RECV_WAIT: begin
                    source_ready <= 1'b1; // NOW we are ready to receive output
                    if (source_valid) begin
                        // Sign extension from 24-bit FFT result to 32-bit SRAM storage
                        capt_real <= {{ (SRAM_DATA_WIDTH - FFT_DATA_WIDTH){source_real[FFT_DATA_WIDTH-1]} }, source_real};
                        capt_imag <= {{ (SRAM_DATA_WIDTH - FFT_DATA_WIDTH){source_imag[FFT_DATA_WIDTH-1]} }, source_imag};

                        if (source_sop) fft_exponent <= source_exp;
                            
                        source_ready <= 1'b0; // De-assert until next write is done
                        state        <= S_WRITE_START;
                    end
                end

                S_WRITE_START: begin
                    wr_addr      <= recv_addr;
                    wr_real_data <= capt_real;
                    wr_imag_data <= capt_imag;
                    wr_start     <= 1'b1;
                    state        <= S_WRITE_WAIT;
                end

                S_WRITE_WAIT: begin
                    if (wr_done) begin
                        if (recv_addr == FFT_N - 1) begin
                            state <= S_COMPLETE;
                        end
                        else begin
                            recv_addr    <= recv_addr + 1'b1;
                            state        <= S_RECV_WAIT;
                        end
                    end
                end

                S_COMPLETE: begin
                    done <= 1'b1; // Inform HPS that operation is finished
                    if (!start) state <= S_IDLE; // Handshake: Wait for HPS to release start
                end

                default: state <= S_IDLE;
            endcase
        end
    end

    // Instanciação — Memory Read Controller: Input SRAM Real
    memory_read_controller #(
        .DATA_WIDTH         (SRAM_DATA_WIDTH),
        .MEM_ADDRESS_N_BITS (ADDR_BITS)
    ) u_read_real (
        .clk            (clk),
        .reset_n        (reset_n),
        .start_read     (rd_start),
        .sram_readdata  (in_real_sram_readdata),
        .data_addr      (rd_addr),
        .mem_write      (in_real_mem_write),
        .data_out       (rd_real_data_out),
        .mem_address    (in_real_mem_address),
        .read_done      (rd_real_done),
        .clken          (in_real_clken),
        .chipselect     (in_real_chipselect)
    );

    // Instanciação — Memory Read Controller: Input SRAM Imag
    memory_read_controller #(
        .DATA_WIDTH         (SRAM_DATA_WIDTH),
        .MEM_ADDRESS_N_BITS (ADDR_BITS)
    ) u_read_imag (
        .clk            (clk),
        .reset_n        (reset_n),
        .start_read     (rd_start),
        .sram_readdata  (in_imag_sram_readdata),
        .data_addr      (rd_addr),
        .mem_write      (in_imag_mem_write),
        .data_out       (rd_imag_data_out),
        .mem_address    (in_imag_mem_address),
        .read_done      (rd_imag_done),
        .clken          (in_imag_clken),
        .chipselect     (in_imag_chipselect)
    );

    // Instanciação — Memory Write Controller: Output SRAM Real
    memory_write_controller #(
        .MEM_ADDRESS_N_BITS (ADDR_BITS),
        .DATA_WIDTH         (SRAM_DATA_WIDTH)
    ) u_write_real (
        .clk            (clk),
        .reset_n        (reset_n),
        .start_write    (wr_start),
        .data_in_addr   (wr_addr),
        .data_in        (wr_real_data),
        .mem_address    (out_real_mem_address),
        .mem_wdata      (out_real_mem_wdata),
        .mem_write      (out_real_mem_write),
        .write_done     (wr_real_done),
        .clken          (out_real_clken),
        .chipselect     (out_real_chipselect)
    );

    // Instanciação — Memory Write Controller: Output SRAM Imag
    memory_write_controller #(
        .MEM_ADDRESS_N_BITS (ADDR_BITS),
        .DATA_WIDTH         (SRAM_DATA_WIDTH)
    ) u_write_imag (
        .clk            (clk),
        .reset_n        (reset_n),
        .start_write    (wr_start),
        .data_in_addr   (wr_addr),
        .data_in        (wr_imag_data),
        .mem_address    (out_imag_mem_address),
        .mem_wdata      (out_imag_mem_wdata),
        .mem_write      (out_imag_mem_write),
        .write_done     (wr_imag_done),
        .clken          (out_imag_clken),
        .chipselect     (out_imag_chipselect)
    );

    // Instanciação — FFT IP Core (Intel/Altera)
    fft_core u_fft (
        .clk          (clk),
        .reset_n      (reset_n),
        .sink_valid   (sink_valid),
        .sink_ready   (sink_ready),
        .sink_error   (sink_error),
        .sink_sop     (sink_sop),
        .sink_eop     (sink_eop),
        .sink_real    (sink_real),
        .sink_imag    (sink_imag),
        .inverse      (inverse_reg),
        .source_valid (source_valid),
        .source_ready (source_ready),
        .source_error (source_error),
        .source_sop   (source_sop),
        .source_eop   (source_eop),
        .source_real  (source_real),
        .source_imag  (source_imag),
        .source_exp   (source_exp)
    );

endmodule
