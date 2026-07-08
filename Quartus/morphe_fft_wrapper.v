// =============================================================================
// morphe_fft_wrapper.v
//
// Lê amostras de fft_xn_re e fft_xn_im,
// envia para o FFT IP Core e salva resultados
// em fft_yn_re e fft_yn_im.
//
// Fluxo:
//   1. HPS escreve amostras em fft_xn_re e fft_xn_im
//   2. HPS pulsa pio_start
//   3. Wrapper lê as amostras via memory_read_controller
//   4. Wrapper alimenta a FFT amostra por amostra
//   5. Wrapper salva resultados via memory_write_controller
//   6. Wrapper pulsa pio_done
//   7. HPS lê resultados de fft_yn_re e fft_yn_im
// =============================================================================

module morphe_fft_wrapper #(
    parameter N                  = 1024,
    parameter DATA_WIDTH         = 16,
    parameter MEM_ADDRESS_N_BITS = 10
)(
    input  wire clk,
    input  wire reset_n,

    // ── Controle via PIO ──────────────────────────────────
    input  wire pio_start,
    output reg  pio_done,

    // ── Interface memória fft_xn_re (leitura) ────────────
    output wire [MEM_ADDRESS_N_BITS-1:0] xn_re_address,
    output wire                          xn_re_clken,
    output wire                          xn_re_chipselect,
    output wire                          xn_re_write,
    input  wire [DATA_WIDTH-1:0]         xn_re_readdata,

    // ── Interface memória fft_xn_im (leitura) ────────────
    output wire [MEM_ADDRESS_N_BITS-1:0] xn_im_address,
    output wire                          xn_im_clken,
    output wire                          xn_im_chipselect,
    output wire                          xn_im_write,
    input  wire [DATA_WIDTH-1:0]         xn_im_readdata,

    // ── Interface memória fft_yn_re (escrita) ────────────
    output wire [MEM_ADDRESS_N_BITS-1:0] yn_re_address,
    output wire [DATA_WIDTH-1:0]         yn_re_wdata,
    output wire                          yn_re_write,
    output wire                          yn_re_clken,
    output wire                          yn_re_chipselect,

    // ── Interface memória fft_yn_im (escrita) ────────────
    output wire [MEM_ADDRESS_N_BITS-1:0] yn_im_address,
    output wire [DATA_WIDTH-1:0]         yn_im_wdata,
    output wire                          yn_im_write,
    output wire                          yn_im_clken,
    output wire                          yn_im_chipselect,

    // ── Interface Avalon-ST FFT sink ──────────────────────
    output reg  [DATA_WIDTH-1:0] sink_real,
    output reg  [DATA_WIDTH-1:0] sink_imag,
    output reg                   sink_valid,
    output reg                   sink_sop,
    output reg                   sink_eop,
    input  wire                  sink_ready,

    // ── Interface Avalon-ST FFT source ───────────────────
    input  wire [DATA_WIDTH-1:0] source_real,
    input  wire [DATA_WIDTH-1:0] source_imag,
    input  wire [5:0]            source_exp,
    input  wire                  source_valid,
    input  wire                  source_eop,
    output wire                  source_ready
);

// ── Fixos ─────────────────────────────────────────────────
assign source_ready = 1'b1;

// =============================================================================
// Sinais internos — controlador de leitura (xn_re)
// =============================================================================

reg                          rd_re_start;
wire [DATA_WIDTH-1:0]        rd_re_data_out;
wire                         rd_re_done;
reg  [MEM_ADDRESS_N_BITS-1:0] rd_re_addr;

memory_read_controller #(
    .DATA_WIDTH         (DATA_WIDTH),
    .MEM_ADDRESS_N_BITS (MEM_ADDRESS_N_BITS)
) u_read_re (
    .clk          (clk),
    .reset_n      (reset_n),
    .start_read   (rd_re_start),
    .sram_readdata(xn_re_readdata),
    .data_addr    (rd_re_addr),
    .mem_write    (xn_re_write),
    .data_out     (rd_re_data_out),
    .mem_address  (xn_re_address),
    .read_done    (rd_re_done),
    .clken        (xn_re_clken),
    .chipselect   (xn_re_chipselect)
);

// =============================================================================
// Sinais internos — controlador de leitura (xn_im)
// =============================================================================

reg                           rd_im_start;
wire [DATA_WIDTH-1:0]         rd_im_data_out;
wire                          rd_im_done;
reg  [MEM_ADDRESS_N_BITS-1:0] rd_im_addr;

memory_read_controller #(
    .DATA_WIDTH         (DATA_WIDTH),
    .MEM_ADDRESS_N_BITS (MEM_ADDRESS_N_BITS)
) u_read_im (
    .clk          (clk),
    .reset_n      (reset_n),
    .start_read   (rd_im_start),
    .sram_readdata(xn_im_readdata),
    .data_addr    (rd_im_addr),
    .mem_write    (xn_im_write),
    .data_out     (rd_im_data_out),
    .mem_address  (xn_im_address),
    .read_done    (rd_im_done),
    .clken        (xn_im_clken),
    .chipselect   (xn_im_chipselect)
);

// =============================================================================
// Sinais internos — controlador de escrita (yn_re)
// =============================================================================

reg                           wr_re_start;
reg  [MEM_ADDRESS_N_BITS-1:0] wr_re_addr;
reg  [DATA_WIDTH-1:0]         wr_re_data;
wire                          wr_re_done;

memory_write_controller #(
    .MEM_ADDRESS_N_BITS (MEM_ADDRESS_N_BITS),
    .DATA_WIDTH         (DATA_WIDTH)
) u_write_re (
    .clk         (clk),
    .reset_n     (reset_n),
    .start_write (wr_re_start),
    .data_in_addr(wr_re_addr),
    .data_in     (wr_re_data),
    .mem_address (yn_re_address),
    .mem_wdata   (yn_re_wdata),
    .mem_write   (yn_re_write),
    .write_done  (wr_re_done),
    .clken       (yn_re_clken),
    .chipselect  (yn_re_chipselect)
);

// =============================================================================
// Sinais internos — controlador de escrita (yn_im)
// =============================================================================

reg                           wr_im_start;
reg  [MEM_ADDRESS_N_BITS-1:0] wr_im_addr;
reg  [DATA_WIDTH-1:0]         wr_im_data;
wire                          wr_im_done;

memory_write_controller #(
    .MEM_ADDRESS_N_BITS (MEM_ADDRESS_N_BITS),
    .DATA_WIDTH         (DATA_WIDTH)
) u_write_im (
    .clk         (clk),
    .reset_n     (reset_n),
    .start_write (wr_im_start),
    .data_in_addr(wr_im_addr),
    .data_in     (wr_im_data),
    .mem_address (yn_im_address),
    .mem_wdata   (yn_im_wdata),
    .mem_write   (yn_im_write),
    .write_done  (wr_im_done),
    .clken       (yn_im_clken),
    .chipselect  (yn_im_chipselect)
);

// =============================================================================
// Máquina de estados principal
// =============================================================================

localparam IDLE        = 4'd0;
localparam READ_XN     = 4'd1;  // dispara leitura de xn_re e xn_im
localparam WAIT_READ   = 4'd2;  // aguarda read_done de ambos
localparam SEND_SAMPLE = 4'd3;  // envia amostra para a FFT
localparam WAIT_RESULT = 4'd4;  // aguarda source_valid
localparam WRITE_RE    = 4'd5;  // dispara escrita em yn_re
localparam WAIT_WR_RE  = 4'd6;  // aguarda write_done de yn_re
localparam WRITE_IM    = 4'd7;  // dispara escrita em yn_im
localparam WAIT_WR_IM  = 4'd8;  // aguarda write_done de yn_im

reg [3:0]                     state;
reg [MEM_ADDRESS_N_BITS-1:0]  sample_cnt;
reg [MEM_ADDRESS_N_BITS-1:0]  result_cnt;
reg [DATA_WIDTH-1:0]          reg_source_real;
reg [DATA_WIDTH-1:0]          reg_source_imag;
reg [5:0]                     reg_source_exp;

always @(posedge clk or negedge reset_n) begin
    if (!reset_n) begin
        state          <= IDLE;
        sample_cnt     <= 0;
        result_cnt     <= 0;
        sink_valid     <= 1'b0;
        sink_sop       <= 1'b0;
        sink_eop       <= 1'b0;
        sink_real      <= 0;
        sink_imag      <= 0;
        pio_done       <= 1'b0;
        rd_re_start    <= 1'b0;
        rd_im_start    <= 1'b0;
        rd_re_addr     <= 0;
        rd_im_addr     <= 0;
        wr_re_start    <= 1'b0;
        wr_im_start    <= 1'b0;
        wr_re_addr     <= 0;
        wr_im_addr     <= 0;
        wr_re_data     <= 0;
        wr_im_data     <= 0;
        reg_source_real<= 0;
        reg_source_imag<= 0;
        reg_source_exp <= 0;
    end
    else begin
        // Defaults — pulsos de 1 ciclo
        sink_sop    <= 1'b0;
        sink_eop    <= 1'b0;
        pio_done    <= 1'b0;
        rd_re_start <= 1'b0;
        rd_im_start <= 1'b0;
        wr_re_start <= 1'b0;
        wr_im_start <= 1'b0;

        case (state)

            // ─────────────────────────────────────────────
            IDLE: begin
                sink_valid <= 1'b0;
                sample_cnt <= 0;
                result_cnt <= 0;

                if (pio_start) begin
                    state <= READ_XN;
                end
            end

            // ─────────────────────────────────────────────
            // Dispara leitura simultânea de xn_re e xn_im
            READ_XN: begin
                rd_re_addr  <= sample_cnt;
                rd_im_addr  <= sample_cnt;
                rd_re_start <= 1'b1;
                rd_im_start <= 1'b1;
                state       <= WAIT_READ;
            end

            // ─────────────────────────────────────────────
            // Aguarda ambos os controladores terminarem
            WAIT_READ: begin
                if (rd_re_done && rd_im_done) begin
                    state <= SEND_SAMPLE;
                end
            end

            // ─────────────────────────────────────────────
            // Envia amostra para a FFT
            SEND_SAMPLE: begin
                if (sink_ready) begin
                    sink_valid <= 1'b1;
                    sink_real  <= rd_re_data_out;
                    sink_imag  <= rd_im_data_out;

                    if (sample_cnt == 0)
                        sink_sop <= 1'b1;

                    if (sample_cnt == N - 1) begin
                        sink_eop   <= 1'b1;
                        sink_valid <= 1'b0;
                        state      <= WAIT_RESULT;
                    end
                    else begin
                        sample_cnt <= sample_cnt + 1;
                        state      <= READ_XN;
                    end
                end
                // sink_ready = 0 → mantém dado estável
            end

            // ─────────────────────────────────────────────
            // Aguarda FFT entregar resultado
            // source_ready fixo em 1 — FFT entrega no ritmo dela
            WAIT_RESULT: begin
                sink_valid <= 1'b0;

                if (source_valid) begin
                    reg_source_real <= source_real;
                    reg_source_imag <= source_imag;
                    reg_source_exp  <= source_exp;
                    state           <= WRITE_RE;
                end
            end

            // ─────────────────────────────────────────────
            // Salva parte real em fft_yn_re
            WRITE_RE: begin
                wr_re_addr  <= result_cnt;
                wr_re_data  <= reg_source_real;
                wr_re_start <= 1'b1;
                state       <= WAIT_WR_RE;
            end

            // ─────────────────────────────────────────────
            // Aguarda escrita de yn_re terminar
            WAIT_WR_RE: begin
                if (wr_re_done) begin
                    state <= WRITE_IM;
                end
            end

            // ─────────────────────────────────────────────
            // Salva parte imaginária em fft_yn_im
            WRITE_IM: begin
                wr_im_addr  <= result_cnt;
                wr_im_data  <= reg_source_imag;
                wr_im_start <= 1'b1;
                state       <= WAIT_WR_IM;
            end

            // ─────────────────────────────────────────────
            // Aguarda escrita de yn_im terminar
            WAIT_WR_IM: begin
                if (wr_im_done) begin
                    result_cnt <= result_cnt + 1;

                    if (source_eop) begin
                        pio_done <= 1'b1;
                        state    <= IDLE;
                    end
                    else begin
                        state <= WAIT_RESULT;
                    end
                end
            end

            default: state <= IDLE;

        endcase
    end
end

endmodule
/*
## Fluxo da máquina de estados
```
IDLE
  │ pio_start=1
  ▼
READ_XN ──── dispara rd_re_start e rd_im_start
  │
  ▼
WAIT_READ ── aguarda rd_re_done AND rd_im_done
  │
  ▼
SEND_SAMPLE ─ sink_ready=1 → envia amostra para FFT
  │                        → se não for última: volta para READ_XN
  │ última amostra (sink_eop)
  ▼
WAIT_RESULT ─ aguarda source_valid
  │
  ▼
WRITE_RE ─── dispara wr_re_start
  │
  ▼
WAIT_WR_RE ─ aguarda wr_re_done
  │
  ▼
WRITE_IM ─── dispara wr_im_start
  │
  ▼
WAIT_WR_IM ─ aguarda wr_im_done
  │           se source_eop → pio_done=1 → IDLE
  │           caso contrário → WAIT_RESULT
  └──────────────────────────────────────────┘
*/