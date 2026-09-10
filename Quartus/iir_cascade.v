// =============================================================================
// iir_cascade.v -- cascata de S secoes de 2a ordem, Q15.16.
//
// Passo 2 do bloco IIR. Le N amostras de uma SRAM, passa cada uma pelas S
// secoes em sequencia e escreve o resultado na SRAM de saida. Os
// coeficientes vem de uma terceira SRAM, 5 palavras por secao, na ordem
//
//     b0 b1 b2 a1 a2   (a0 = 1 implicito, o projetista normaliza)
//
// POR QUE CASCATA, E NAO UM FILTRO DE ORDEM N DIRETO
// --------------------------------------------------
// A posicao dos polos de um polinomio de ordem N e absurdamente sensivel
// aos coeficientes dele, e a sensibilidade cresce com a ordem. Medido no
// proprio MATLAB do Prof. Sanca: um Butterworth de ordem 22, estavel por
// construcao, volta de la com um polo em |p| = 1,278 -- instavel -- porque
// achar raizes daquele polinomio ja e mal condicionado em ponto flutuante
// de 64 bits. A mesma especificacao em secoes de 2a ordem da |p| = 0,988.
// Em ponto fixo de 32 bits nao haveria conversa.
//
// POR QUE AMOSTRA POR FORA E SECAO POR DENTRO
// -------------------------------------------
// Duas ordens de varredura sao possiveis:
//
//   (a) secao por fora: roda a cascata inteira secao a secao, cada uma
//       lendo o vetor completo da anterior. Precisa de um buffer extra do
//       tamanho do sinal e de S passagens pela memoria.
//   (b) amostra por fora: para cada amostra, atravessa as S secoes de uma
//       vez. Uma unica passagem, sem buffer -- so os 4 registradores de
//       estado por secao.
//
// Aqui e (b). O resultado e identico ao (a) bit a bit, e nao por
// aproximacao: a secao s so enxerga a saida ja arredondada da secao s-1,
// que e a mesma nos dois esquemas. O modelo em Python usa (a) e serve de
// referencia justamente por isso.
//
// CUSTO
// -----
// Um unico iir_biquad_mac, compartilhado no tempo entre as secoes: 5
// blocos DSP, independentemente de S. O preco e 1 ciclo por secao por
// amostra, o que e barato perto dos ~13 ciclos que as memorias custam.
//
// Estado zerado a cada start: sem isso o resultado dependeria da rodada
// anterior, e o mesmo sinal daria saidas diferentes.
// =============================================================================

`timescale 1 ns / 1 ps

module iir_cascade #(
    parameter DATA_WIDTH   = 32,
    parameter FRAC_BITS    = 16,
    parameter ACC_WIDTH    = 72,
    parameter N_SAMPLES    = 1024,
    parameter ADDR_N_BITS  = 10,
    parameter MAX_SECOES   = 16,    // ordem 32; o estudo nunca passou de 11
    parameter COEF_ADDR_N_BITS = 8  // 5 * MAX_SECOES enderecos
)(
    input  wire                          clk,
    input  wire                          reset_n,
    input  wire                          start,
    output reg                           done,
    output reg                           error_sat,

    // Quantas secoes usar nesta execucao (1..MAX_SECOES).
    input  wire [$clog2(MAX_SECOES+1)-1:0] n_secoes,

    // --- SRAM dos coeficientes: 5 palavras por secao ---
    input  wire [DATA_WIDTH-1:0]         coef_sram_readdata,
    output wire [COEF_ADDR_N_BITS-1:0]   coef_sram_address,
    output wire                          coef_sram_chipselect,
    output wire                          coef_sram_clken,
    output wire                          coef_sram_write,

    // --- SRAM de entrada x[n] ---
    input  wire [DATA_WIDTH-1:0]         xn_sram_readdata,
    output wire [ADDR_N_BITS-1:0]        xn_sram_address,
    output wire                          xn_sram_chipselect,
    output wire                          xn_sram_clken,
    output wire                          xn_sram_write,

    // --- SRAM de saida y[n] ---
    output wire [ADDR_N_BITS-1:0]        yn_sram_address,
    output wire [DATA_WIDTH-1:0]         yn_sram_wdata,
    output wire                          yn_sram_chipselect,
    output wire                          yn_sram_clken,
    output wire                          yn_sram_write,

    output wire [3:0]                    debug_state
);

    localparam [3:0] S_IDLE       = 4'd0;
    localparam [3:0] S_COEF_RD    = 4'd1;  // le uma palavra de coeficiente
    localparam [3:0] S_COEF_WAIT  = 4'd2;
    localparam [3:0] S_READ       = 4'd3;
    localparam [3:0] S_WAIT_READ  = 4'd4;
    localparam [3:0] S_MAC        = 4'd5;  // uma secao por ciclo
    localparam [3:0] S_WRITE      = 4'd6;
    localparam [3:0] S_WAIT_WRITE = 4'd7;
    localparam [3:0] S_DONE       = 4'd8;

    reg [3:0] state;
    assign debug_state = state;

    localparam SEC_BITS = $clog2(MAX_SECOES + 1);

    reg [ADDR_N_BITS-1:0]      n;      // amostra corrente
    reg [SEC_BITS-1:0]         s;      // secao corrente
    reg [COEF_ADDR_N_BITS-1:0] c_idx;  // palavra de coeficiente na carga

    reg start_d;
    wire start_pulse = start & ~start_d;
    always @(posedge clk or negedge reset_n) begin
        if (!reset_n) start_d <= 1'b0;
        else          start_d <= start;
    end

    // --- Coeficientes, carregados uma vez por execucao ---
    // Em registradores, e nao lidos a cada uso: reler 5 palavras por secao
    // por amostra custaria mais ciclos de memoria que a conta inteira.
    reg signed [DATA_WIDTH-1:0] cb0 [0:MAX_SECOES-1];
    reg signed [DATA_WIDTH-1:0] cb1 [0:MAX_SECOES-1];
    reg signed [DATA_WIDTH-1:0] cb2 [0:MAX_SECOES-1];
    reg signed [DATA_WIDTH-1:0] ca1 [0:MAX_SECOES-1];
    reg signed [DATA_WIDTH-1:0] ca2 [0:MAX_SECOES-1];

    // --- Estado da Forma Direta I, um conjunto por secao ---
    reg signed [DATA_WIDTH-1:0] sx1 [0:MAX_SECOES-1];
    reg signed [DATA_WIDTH-1:0] sx2 [0:MAX_SECOES-1];
    reg signed [DATA_WIDTH-1:0] sy1 [0:MAX_SECOES-1];
    reg signed [DATA_WIDTH-1:0] sy2 [0:MAX_SECOES-1];

    // Amostra circulando entre as secoes: entra x[n], sai y[n].
    reg signed [DATA_WIDTH-1:0] amostra;

    integer k;

    // --- Controle das memorias ---
    reg                          cf_start;
    reg  [COEF_ADDR_N_BITS-1:0]  cf_addr;
    wire [DATA_WIDTH-1:0]        cf_data;
    wire                         cf_done;

    reg                          rd_start;
    reg  [ADDR_N_BITS-1:0]       rd_addr;
    wire [DATA_WIDTH-1:0]        rd_data;
    wire                         rd_done;

    reg                          wr_start;
    reg  [ADDR_N_BITS-1:0]       wr_addr;
    reg  [DATA_WIDTH-1:0]        wr_data;
    wire                         wr_done;

    // --- Caminho de dados, o MESMO do iir_sos ---
    wire signed [DATA_WIDTH-1:0] yn;
    wire                         estourou;

    iir_biquad_mac #(
        .DATA_WIDTH (DATA_WIDTH),
        .FRAC_BITS  (FRAC_BITS),
        .ACC_WIDTH  (ACC_WIDTH)
    ) u_mac (
        .xn (amostra),
        .x1 (sx1[s]), .x2 (sx2[s]),
        .y1 (sy1[s]), .y2 (sy2[s]),
        .b0 (cb0[s]), .b1 (cb1[s]), .b2 (cb2[s]),
        .a1 (ca1[s]), .a2 (ca2[s]),
        .yn (yn), .saturou (estourou)
    );

    always @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            state     <= S_IDLE;
            done      <= 1'b0;
            error_sat <= 1'b0;
            n <= 0; s <= 0; c_idx <= 0;
            amostra <= 0;
            cf_start <= 1'b0; rd_start <= 1'b0; wr_start <= 1'b0;
            cf_addr <= 0; rd_addr <= 0; wr_addr <= 0; wr_data <= 0;
            for (k = 0; k < MAX_SECOES; k = k + 1) begin
                sx1[k] <= 0; sx2[k] <= 0; sy1[k] <= 0; sy2[k] <= 0;
            end
        end else begin
            cf_start <= 1'b0;
            rd_start <= 1'b0;
            wr_start <= 1'b0;

            case (state)
                S_IDLE: begin
                    done <= 1'b0;
                    if (start_pulse) begin
                        n <= 0; s <= 0; c_idx <= 0;
                        error_sat <= 1'b0;
                        for (k = 0; k < MAX_SECOES; k = k + 1) begin
                            sx1[k] <= 0; sx2[k] <= 0;
                            sy1[k] <= 0; sy2[k] <= 0;
                        end
                        state <= S_COEF_RD;
                    end
                end

                // ---- carga dos coeficientes: 5 palavras por secao ----
                S_COEF_RD: begin
                    cf_addr  <= c_idx;
                    cf_start <= 1'b1;
                    state    <= S_COEF_WAIT;
                end

                S_COEF_WAIT: begin
                    if (cf_done) begin
                        case (c_idx % 5)
                            0: cb0[c_idx / 5] <= cf_data;
                            1: cb1[c_idx / 5] <= cf_data;
                            2: cb2[c_idx / 5] <= cf_data;
                            3: ca1[c_idx / 5] <= cf_data;
                            4: ca2[c_idx / 5] <= cf_data;
                        endcase
                        if (c_idx == (n_secoes * 5) - 1) begin
                            c_idx <= 0;
                            state <= S_READ;
                        end else begin
                            c_idx <= c_idx + 1'b1;
                            state <= S_COEF_RD;
                        end
                    end
                end

                // ---- uma amostra ----
                S_READ: begin
                    rd_addr  <= n;
                    rd_start <= 1'b1;
                    state    <= S_WAIT_READ;
                end

                S_WAIT_READ: begin
                    if (rd_done) begin
                        amostra <= rd_data;
                        s       <= 0;
                        state   <= S_MAC;
                    end
                end

                // Uma secao por ciclo. A saida de uma vira a entrada da
                // proxima na mesma amostra -- e o que faz a cascata ser
                // uma passagem so.
                S_MAC: begin
                    if (estourou) error_sat <= 1'b1;
                    sx2[s] <= sx1[s];  sx1[s] <= amostra;
                    sy2[s] <= sy1[s];  sy1[s] <= yn;
                    amostra <= yn;
                    if (s == n_secoes - 1) begin
                        wr_data <= yn;
                        state   <= S_WRITE;
                    end else begin
                        s <= s + 1'b1;
                    end
                end

                S_WRITE: begin
                    wr_addr  <= n;
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

                S_DONE: begin
                    done <= 1'b1;
                    if (!start) state <= S_IDLE;
                end

                default: state <= S_IDLE;
            endcase
        end
    end

    // --- Controladores de memoria, os mesmos do conv1d ---
    memory_read_controller #(
        .DATA_WIDTH         (DATA_WIDTH),
        .MEM_ADDRESS_N_BITS (COEF_ADDR_N_BITS)
    ) u_rd_coef (
        .clk (clk), .reset_n (reset_n),
        .start_read    (cf_start),
        .sram_readdata (coef_sram_readdata),
        .data_addr     (cf_addr),
        .mem_write     (coef_sram_write),
        .data_out      (cf_data),
        .mem_address   (coef_sram_address),
        .read_done     (cf_done),
        .clken         (coef_sram_clken),
        .chipselect    (coef_sram_chipselect)
    );

    memory_read_controller #(
        .DATA_WIDTH         (DATA_WIDTH),
        .MEM_ADDRESS_N_BITS (ADDR_N_BITS)
    ) u_rd_x (
        .clk (clk), .reset_n (reset_n),
        .start_read    (rd_start),
        .sram_readdata (xn_sram_readdata),
        .data_addr     (rd_addr),
        .mem_write     (xn_sram_write),
        .data_out      (rd_data),
        .mem_address   (xn_sram_address),
        .read_done     (rd_done),
        .clken         (xn_sram_clken),
        .chipselect    (xn_sram_chipselect)
    );

    memory_write_controller #(
        .DATA_WIDTH         (DATA_WIDTH),
        .MEM_ADDRESS_N_BITS (ADDR_N_BITS)
    ) u_wr (
        .clk (clk), .reset_n (reset_n),
        .start_write  (wr_start),
        .data_in_addr (wr_addr),
        .data_in      (wr_data),
        .write_done   (wr_done),
        .mem_address  (yn_sram_address),
        .mem_wdata    (yn_sram_wdata),
        .mem_write    (yn_sram_write),
        .clken        (yn_sram_clken),
        .chipselect   (yn_sram_chipselect)
    );

endmodule
