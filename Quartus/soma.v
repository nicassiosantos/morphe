// =============================================================================
// soma.v -- soma de dois sinais, amostra a amostra: y[n] = a[n] + b[n].
//
// Modulo de exemplo do roteiro "Como adicionar um modulo ao Morphe"
// (docs/roteiro-modulo). A conta e trivial de proposito: o que interessa e o
// caminho inteiro -- memorias, PIOs, servidor e cliente --, que e o mesmo de
// qualquer acelerador.
//
// Como conversa com o resto:
//   - tres memorias de porta dupla do Platform Designer (soma_a, soma_b,
//     soma_y), 1024 palavras de 32 bits cada. O HPS escreve a e b e le y pela
//     porta s2; este modulo usa a porta s1, exportada para o ghrd_top;
//   - dois PIOs: soma_start (HPS -> FPGA) e soma_done (FPGA -> HPS).
//
// Protocolo de start/done, o mesmo do IIR e do conv1d:
//   1. o HPS escreve as entradas e poe start = 1 (borda de subida dispara);
//   2. o modulo processa SEMPRE N_SAMPLES amostras (o servidor completa com
//      zeros o que o cliente nao mandou) e entao poe done = 1;
//   3. o HPS le a saida e poe start = 0; com start em 0, done volta a 0.
//
// A conta (Q15.16, com saturacao) fica no soma_core.v; este modulo so le a[n]
// e b[n] das memorias, passa pelo nucleo e grava y[n].
//
// Leitura e escrita das memorias: os mesmos memory_read_controller e
// memory_write_controller que o conv1d e o iir_cascade usam. Cada leitura
// custa 6 ciclos e cada escrita 4, contando a ida e a volta pela maquina de
// estados; a e b sao lidas em paralelo, por dois controladores. Uma amostra
// custa 12 ciclos: 1024 amostras em 12 289 ciclos, ~0,25 ms a 50 MHz.
// =============================================================================

`timescale 1 ns / 1 ps

module soma #(
    parameter DATA_WIDTH  = 32,
    parameter N_SAMPLES   = 1024,
    parameter ADDR_N_BITS = 10
)(
    input  wire                     clk,
    input  wire                     reset_n,
    input  wire                     start,
    output reg                      done,

    // --- memoria da entrada a[n] (so leitura) ---
    input  wire [DATA_WIDTH-1:0]    a_sram_readdata,
    output wire [ADDR_N_BITS-1:0]   a_sram_address,
    output wire                     a_sram_chipselect,
    output wire                     a_sram_clken,
    output wire                     a_sram_write,

    // --- memoria da entrada b[n] (so leitura) ---
    input  wire [DATA_WIDTH-1:0]    b_sram_readdata,
    output wire [ADDR_N_BITS-1:0]   b_sram_address,
    output wire                     b_sram_chipselect,
    output wire                     b_sram_clken,
    output wire                     b_sram_write,

    // --- memoria da saida y[n] (so escrita) ---
    output wire [ADDR_N_BITS-1:0]   y_sram_address,
    output wire [DATA_WIDTH-1:0]    y_sram_wdata,
    output wire                     y_sram_chipselect,
    output wire                     y_sram_clken,
    output wire                     y_sram_write
);

    localparam [2:0] S_IDLE       = 3'd0;
    localparam [2:0] S_READ       = 3'd1;  // pede a[n] e b[n]
    localparam [2:0] S_WAIT_READ  = 3'd2;
    localparam [2:0] S_WRITE      = 3'd3;  // grava y[n]
    localparam [2:0] S_WAIT_WRITE = 3'd4;
    localparam [2:0] S_DONE       = 3'd5;

    reg [2:0] state;
    reg [ADDR_N_BITS-1:0] n;    // amostra corrente

    // start dispara na borda de subida: um start que ficou em 1 da rodada
    // anterior nao dispara outra.
    reg start_d;
    wire start_pulse = start & ~start_d;
    always @(posedge clk or negedge reset_n) begin
        if (!reset_n) start_d <= 1'b0;
        else          start_d <= start;
    end

    // --- controle das memorias ---
    reg                     rd_start;
    wire [DATA_WIDTH-1:0]   a_data, b_data;
    wire                    a_done, b_done;

    reg                     wr_start;
    reg  [DATA_WIDTH-1:0]   wr_data;
    wire                    wr_done;

    // --- a conta: o mesmo nucleo testado sozinho na Parte A do roteiro ---
    wire [DATA_WIDTH-1:0] soma_sat;

    soma_core #(.DATA_WIDTH(DATA_WIDTH)) u_conta (
        .a (a_data),
        .b (b_data),
        .y (soma_sat)
    );

    always @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            state    <= S_IDLE;
            done     <= 1'b0;
            n        <= 0;
            rd_start <= 1'b0;
            wr_start <= 1'b0;
            wr_data  <= 0;
        end else begin
            rd_start <= 1'b0;
            wr_start <= 1'b0;

            case (state)
                S_IDLE: begin
                    done <= 1'b0;
                    if (start_pulse) begin
                        n     <= 0;
                        state <= S_READ;
                    end
                end

                // Os dois controladores recebem o mesmo endereco e o mesmo
                // pulso, e terminam no mesmo ciclo.
                S_READ: begin
                    rd_start <= 1'b1;
                    state    <= S_WAIT_READ;
                end

                S_WAIT_READ: begin
                    if (a_done && b_done) begin
                        wr_data <= soma_sat;
                        state   <= S_WRITE;
                    end
                end

                S_WRITE: begin
                    wr_start <= 1'b1;
                    state    <= S_WAIT_WRITE;
                end

                S_WAIT_WRITE: begin
                    if (wr_done) begin
                        if (n == N_SAMPLES - 1) begin
                            state <= S_DONE;
                        end else begin
                            n     <= n + 1'b1;
                            state <= S_READ;
                        end
                    end
                end

                // done fica em 1 ate o HPS baixar o start.
                S_DONE: begin
                    done <= 1'b1;
                    if (!start) state <= S_IDLE;
                end

                default: state <= S_IDLE;
            endcase
        end
    end

    // --- controladores de memoria: os mesmos do conv1d e do iir_cascade ---
    memory_read_controller #(
        .DATA_WIDTH         (DATA_WIDTH),
        .MEM_ADDRESS_N_BITS (ADDR_N_BITS)
    ) u_rd_a (
        .clk (clk), .reset_n (reset_n),
        .start_read    (rd_start),
        .sram_readdata (a_sram_readdata),
        .data_addr     (n),
        .mem_write     (a_sram_write),
        .data_out      (a_data),
        .mem_address   (a_sram_address),
        .read_done     (a_done),
        .clken         (a_sram_clken),
        .chipselect    (a_sram_chipselect)
    );

    memory_read_controller #(
        .DATA_WIDTH         (DATA_WIDTH),
        .MEM_ADDRESS_N_BITS (ADDR_N_BITS)
    ) u_rd_b (
        .clk (clk), .reset_n (reset_n),
        .start_read    (rd_start),
        .sram_readdata (b_sram_readdata),
        .data_addr     (n),
        .mem_write     (b_sram_write),
        .data_out      (b_data),
        .mem_address   (b_sram_address),
        .read_done     (b_done),
        .clken         (b_sram_clken),
        .chipselect    (b_sram_chipselect)
    );

    memory_write_controller #(
        .DATA_WIDTH         (DATA_WIDTH),
        .MEM_ADDRESS_N_BITS (ADDR_N_BITS)
    ) u_wr_y (
        .clk (clk), .reset_n (reset_n),
        .start_write  (wr_start),
        .data_in_addr (n),
        .data_in      (wr_data),
        .write_done   (wr_done),
        .mem_address  (y_sram_address),
        .mem_wdata    (y_sram_wdata),
        .mem_write    (y_sram_write),
        .clken        (y_sram_clken),
        .chipselect   (y_sram_chipselect)
    );

endmodule
