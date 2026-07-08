// ============================================================================
// fft_impulse_test.v
//
// Módulo de teste que envia um impulso unitário (amostra 0 = 1, demais = 0)
// diretamente ao FFT Core, e escreve os resultados nas SRAMs de saída
// usando os módulos memory_write_controller.
//
// Resultado esperado: todos os 1024 bins com real=1, imag=0 (resposta ao
// impulso de uma FFT é constante em todos os bins).
//
// ============================================================================

module fft_impulse_test #(
    parameter FFT_N      = 1024,
    parameter DATA_WIDTH = 16,
    parameter ADDR_BITS  = 10,
    parameter EXP_WIDTH  = 6
)(
    input wire clk,
    input wire reset_n,

    // Controle
    input  wire                    start,
    output reg                     done,
    output reg  [EXP_WIDTH-1:0]    fft_exponent,

    // Output SRAM Real — porta B (via memory_write_controller)
    output wire [ADDR_BITS-1:0]    out_real_mem_address,
    output wire [DATA_WIDTH-1:0]   out_real_mem_wdata,
    output wire                    out_real_mem_write,
    output wire                    out_real_clken,
    output wire                    out_real_chipselect,

    // Output SRAM Imag — porta B (via memory_write_controller)
    output wire [ADDR_BITS-1:0]    out_imag_mem_address,
    output wire [DATA_WIDTH-1:0]   out_imag_mem_wdata,
    output wire                    out_imag_mem_write,
    output wire                    out_imag_clken,
    output wire                    out_imag_chipselect,

    // Debug
    output wire [3:0]              debug_state,
    output wire                    debug_source_valid,
    output wire                    debug_sink_ready
);

    // ========================================================================
    // Estados da FSM
    // ========================================================================
    localparam S_IDLE        = 4'd0;
    localparam S_FEED        = 4'd1;   // Alimenta amostra ao FFT
    localparam S_RECV_WAIT   = 4'd2;   // Aguarda source_valid
    localparam S_WRITE_START = 4'd3;   // Dispara memory_write_controllers
    localparam S_WRITE_WAIT  = 4'd4;   // Aguarda write_done
    localparam S_COMPLETE    = 4'd5;

    reg [3:0] state;
    assign debug_state = state;

    // ========================================================================
    // Contadores
    // ========================================================================
    reg [ADDR_BITS-1:0] feed_count;
    reg [ADDR_BITS-1:0] recv_count;

    // ========================================================================
    // Detecção de borda de subida do start
    // ========================================================================
    reg start_prev;
    wire start_rising = start & ~start_prev;

    always @(posedge clk or negedge reset_n) begin
        if (!reset_n)
            start_prev <= 1'b0;
        else
            start_prev <= start;
    end

    // ========================================================================
    // Sinais do FFT Core
    // ========================================================================
    reg                         sink_valid;
    wire                        sink_ready;
    reg  [1:0]                  sink_error;
    reg                         sink_sop;
    reg                         sink_eop;
    reg  [DATA_WIDTH-1:0]       sink_real;
    reg  [DATA_WIDTH-1:0]       sink_imag;

    wire                        source_valid;
    reg                         source_ready;
    wire [1:0]                  source_error;
    wire                        source_sop;
    wire                        source_eop;
    wire [DATA_WIDTH-1:0]       source_real;
    wire [DATA_WIDTH-1:0]       source_imag;
    wire [EXP_WIDTH-1:0]        source_exp;

    assign debug_source_valid = source_valid;
    assign debug_sink_ready   = sink_ready;

    // ========================================================================
    // Sinais dos Memory Write Controllers
    // ========================================================================
    reg                    wr_start;
    reg  [ADDR_BITS-1:0]  wr_addr;
    reg  [DATA_WIDTH-1:0]  wr_real_data;
    reg  [DATA_WIDTH-1:0]  wr_imag_data;

    wire                   wr_real_done;
    wire                   wr_imag_done;
    wire                   wr_done = wr_real_done & wr_imag_done;

    // Registros de captura
    reg [DATA_WIDTH-1:0]   capt_real;
    reg [DATA_WIDTH-1:0]   capt_imag;

// ========================================================================
    // FSM Principal
    // ========================================================================
    always @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            state        <= S_IDLE;
            done         <= 1'b0;
            fft_exponent <= {EXP_WIDTH{1'b0}};
            feed_count   <= {ADDR_BITS{1'b0}};
            recv_count   <= {ADDR_BITS{1'b0}};

            sink_valid   <= 1'b0;
            sink_error   <= 2'b00;
            sink_sop     <= 1'b0;
            sink_eop     <= 1'b0;
            sink_real    <= {DATA_WIDTH{1'b0}};
            sink_imag    <= {DATA_WIDTH{1'b0}};

            source_ready <= 1'b0;

            capt_real    <= {DATA_WIDTH{1'b0}};
            capt_imag    <= {DATA_WIDTH{1'b0}};

            wr_start     <= 1'b0;
            wr_addr      <= {ADDR_BITS{1'b0}};
            wr_real_data <= {DATA_WIDTH{1'b0}};
            wr_imag_data <= {DATA_WIDTH{1'b0}};
        end
        else begin
            // Default: pulsos de 1 ciclo
            sink_valid <= 1'b0;
            wr_start   <= 1'b0;

            case (state)
                // ============================================================
                // IDLE
                // ============================================================
                S_IDLE: begin
                    done         <= 1'b0;
                    source_ready <= 1'b0;

                    if (start_rising) begin
                        feed_count   <= {ADDR_BITS{1'b0}};
                        recv_count   <= {ADDR_BITS{1'b0}};
                        source_ready <= 1'b1;
                        
                        // PRE-LOAD THE FIRST SAMPLE: 
                        // It will be ready on the bus the exact moment we enter S_FEED
                        sink_valid   <= 1'b1;
                        sink_sop     <= 1'b1;
                        sink_eop     <= 1'b0;
                        sink_error   <= 2'b00;
                        sink_real    <= 16'd10000; // Loud impulse to survive truncation
                        sink_imag    <= 16'd0;

                        state        <= S_FEED;
                    end
                end

                // ============================================================
                // FEED: Alimenta amostras ao FFT Core
                // ============================================================
                S_FEED: begin
                    // Hold valid high while we are feeding
                    sink_valid <= 1'b1; 

                    if (sink_ready) begin
                        if (feed_count == FFT_N - 1) begin
                            // The core just accepted the EOP! The packet is complete.
                            sink_valid <= 1'b0;
                            state      <= S_RECV_WAIT;
                        end
                        else begin
                            // The core accepted sample N. Prepare sample N+1 for the next cycle.
                            feed_count <= feed_count + 1'b1;
                            
                            sink_sop   <= 1'b0; 
                            sink_eop   <= (feed_count + 1'b1 == FFT_N - 1);
                            sink_real  <= 16'd0; // All samples after index 0 are zero
                            sink_imag  <= 16'd0;
                        end
                    end
                end

                // ============================================================
                // RECV_WAIT: Aguarda resultado do FFT Core
                // ============================================================
                S_RECV_WAIT: begin
                    // source_ready permanece em 1

                    if (source_valid) begin
                        capt_real <= source_real;
                        capt_imag <= source_imag;

                        if (source_sop)
                            fft_exponent <= source_exp;

                        source_ready <= 1'b0; // Pause FFT while we write
                        state        <= S_WRITE_START;
                    end
                end

                // ============================================================
                // WRITE_START: Dispara escrita via memory_write_controllers
                // ============================================================
                S_WRITE_START: begin
                    wr_addr      <= recv_count;
                    wr_real_data <= capt_real;
                    wr_imag_data <= capt_imag;
                    wr_start     <= 1'b1;
                    state        <= S_WRITE_WAIT;
                end

                // ============================================================
                // WRITE_WAIT: Aguarda conclusão dos write controllers
                // ============================================================
                S_WRITE_WAIT: begin
                    if (wr_done) begin
                        if (recv_count == FFT_N - 1) begin
                            state <= S_COMPLETE;
                        end
                        else begin
                            recv_count   <= recv_count + 1'b1;
                            source_ready <= 1'b1; // Wake FFT up for the next result
                            state        <= S_RECV_WAIT;
                        end
                    end
                end

                // ============================================================
                // COMPLETE
                // ============================================================
                S_COMPLETE: begin
                    done         <= 1'b1;
                    source_ready <= 1'b0;

                    if (!start)
                        state <= S_IDLE;
                end

                default: state <= S_IDLE;
            endcase
        end
    end

    // ========================================================================
    // Instanciação — Memory Write Controller: Output SRAM Real
    // ========================================================================
    memory_write_controller #(
        .MEM_ADDRESS_N_BITS (ADDR_BITS),
        .DATA_WIDTH         (DATA_WIDTH)
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

    // ========================================================================
    // Instanciação — Memory Write Controller: Output SRAM Imag
    // ========================================================================
    memory_write_controller #(
        .MEM_ADDRESS_N_BITS (ADDR_BITS),
        .DATA_WIDTH         (DATA_WIDTH)
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

    // ========================================================================
    // Instanciação — FFT IP Core
    // ========================================================================
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
        .inverse      (1'b0),          // FFT direta (não IFFT)
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