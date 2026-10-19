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
// blocos DSP, independentemente de S. O preco e 2 ciclos por secao por
// amostra, o que e barato perto dos ~13 ciclos que as memorias custam.
//
// POR QUE 2 CICLOS POR SECAO, E NAO 1
// -----------------------------------
// A primeira versao fazia tudo num ciclo: selecionar os operandos da secao
// s (nove multiplexadores de MAX_SECOES entradas), multiplicar, somar,
// arredondar, saturar e escrever de volta em sy1[s]. Medido no Quartus em
// 14/09/2026: 19,7 ns de logica num periodo de 20 ns, Fmax 49,11 MHz --
// nao fecha a 50 MHz. Os 15 piores caminhos saiam do registrador s.
//
// Agora o estado S_SEL copia os operandos de [s] para registradores planos
// e o S_MAC calcula a partir deles. O multiplexador sai do caminho critico
// e o Quartus mede as duas metades separadamente. O resultado e bit a bit
// o mesmo: mudou quando a conta acontece, nao a conta.
//
// ESTADO ENTRE EXECUCOES (19/10/2026)
// -----------------------------------
// O bloco processa N_SAMPLES por vez. Para um sinal maior, o cliente parte
// em blocos -- e um IIR tem memoria: cada bloco precisa comecar do estado
// em que o anterior terminou. Antes, o estado era zerado a cada start e o
// cliente o RECONSTRUIA reprocessando amostras do bloco anterior
// (aquecimento), o que nao cabe no bloco quando os polos estao perto do
// circulo unitario. Agora o estado vai e volta pela SRAM dos coeficientes,
// que tem 256 palavras e so usa 5 * MAX_SECOES:
//
//     EST_MODO     palavra de modo, escrita pelo HPS: bit 0 = 1 carrega o
//                  estado inicial de EST_IN; 0 = estado zero (o de sempre)
//     EST_MARCA    escrita pelo BLOCO ao fim: EST_MARCA_VALOR diz ao
//                  servidor que este bitstream devolve o estado
//     EST_IN ..    estado inicial, 4 palavras por secao: x1 x2 y1 y2
//     EST_OUT ..   estado final, mesmo formato, escrito ao fim de TODA
//                  execucao (o estado depois da ultima das N_SAMPLES)
//
// Carregar o estado final de um bloco como inicial do seguinte da a MESMA
// saida, bit a bit, que processar os dois de uma vez: os registradores sao
// a memoria inteira da Forma Direta I. Nada no Platform Designer mudou.
//
// Com o modo em 0 o estado e zerado a cada start, como antes: sem isso o
// resultado dependeria da rodada anterior.
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

    // --- SRAM dos coeficientes: 5 palavras por secao, e o estado ---
    input  wire [DATA_WIDTH-1:0]         coef_sram_readdata,
    output wire [COEF_ADDR_N_BITS-1:0]   coef_sram_address,
    output wire                          coef_sram_chipselect,
    output wire                          coef_sram_clken,
    output wire                          coef_sram_write,
    output wire [DATA_WIDTH-1:0]         coef_sram_wdata,

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
    localparam [3:0] S_MAC        = 4'd5;  // calcula a secao s
    localparam [3:0] S_WRITE      = 4'd6;
    localparam [3:0] S_WAIT_WRITE = 4'd7;
    localparam [3:0] S_DONE       = 4'd8;
    localparam [3:0] S_SEL        = 4'd9;  // seleciona os operandos da secao s
    localparam [3:0] S_MODO_RD    = 4'd10; // le a palavra de modo
    localparam [3:0] S_MODO_WAIT  = 4'd11;
    localparam [3:0] S_EST_RD     = 4'd12; // carrega uma palavra do estado inicial
    localparam [3:0] S_EST_WAIT   = 4'd13;
    localparam [3:0] S_EST_WR     = 4'd14; // grava uma palavra do estado final
    localparam [3:0] S_EST_WR_WAIT = 4'd15;

    // Mapa da SRAM dos coeficientes (ver o cabecalho). Pede
    // COEF_ADDR_N_BITS >= 8 e MAX_SECOES <= 16.
    localparam [COEF_ADDR_N_BITS-1:0] EST_MODO  = 120;
    localparam [COEF_ADDR_N_BITS-1:0] EST_MARCA = 121;
    localparam [COEF_ADDR_N_BITS-1:0] EST_IN    = 128;
    localparam [COEF_ADDR_N_BITS-1:0] EST_OUT   = 192;
    localparam [DATA_WIDTH-1:0]       EST_MARCA_VALOR = 32'h45535431;  // "EST1"

    reg [3:0] state;
    assign debug_state = state;

    localparam SEC_BITS = $clog2(MAX_SECOES + 1);
    localparam EST_BITS = $clog2(4 * MAX_SECOES + 1);

    reg [ADDR_N_BITS-1:0]      n;      // amostra corrente
    reg [SEC_BITS-1:0]         s;      // secao corrente
    reg [COEF_ADDR_N_BITS-1:0] c_idx;  // palavra de coeficiente na carga
    reg [EST_BITS-1:0]         e_idx;  // palavra do estado: secao = e_idx/4

    // 4 palavras por secao em uso: x1 x2 y1 y2
    wire [EST_BITS-1:0] n_est = {n_secoes, 2'b00};
    wire [EST_BITS-3:0] e_sec = e_idx[EST_BITS-1:2];
    wire [1:0]          e_qual = e_idx[1:0];

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

    // Operandos da secao corrente, copiados de [s] no S_SEL. E este
    // estagio que tira o multiplexador por s do caminho critico.
    reg signed [DATA_WIDTH-1:0] op_x1, op_x2, op_y1, op_y2;
    reg signed [DATA_WIDTH-1:0] op_b0, op_b1, op_b2, op_a1, op_a2;

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

    // escrita na SRAM dos coeficientes: so o estado final e a marca
    reg                          cw_start;
    reg  [COEF_ADDR_N_BITS-1:0]  cw_addr;
    reg  [DATA_WIDTH-1:0]        cw_data;
    wire                         cw_done;

    // --- Caminho de dados, o MESMO do iir_sos ---
    wire signed [DATA_WIDTH-1:0] yn;
    wire                         estourou;

    iir_biquad_mac #(
        .DATA_WIDTH (DATA_WIDTH),
        .FRAC_BITS  (FRAC_BITS),
        .ACC_WIDTH  (ACC_WIDTH)
    ) u_mac (
        .xn (amostra),
        .x1 (op_x1), .x2 (op_x2),
        .y1 (op_y1), .y2 (op_y2),
        .b0 (op_b0), .b1 (op_b1), .b2 (op_b2),
        .a1 (op_a1), .a2 (op_a2),
        .yn (yn), .saturou (estourou)
    );

    always @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            state     <= S_IDLE;
            done      <= 1'b0;
            error_sat <= 1'b0;
            n <= 0; s <= 0; c_idx <= 0; e_idx <= 0;
            amostra <= 0;
            op_x1 <= 0; op_x2 <= 0; op_y1 <= 0; op_y2 <= 0;
            op_b0 <= 0; op_b1 <= 0; op_b2 <= 0; op_a1 <= 0; op_a2 <= 0;
            cf_start <= 1'b0; rd_start <= 1'b0; wr_start <= 1'b0; cw_start <= 1'b0;
            cf_addr <= 0; rd_addr <= 0; wr_addr <= 0; wr_data <= 0;
            cw_addr <= 0; cw_data <= 0;
            for (k = 0; k < MAX_SECOES; k = k + 1) begin
                sx1[k] <= 0; sx2[k] <= 0; sy1[k] <= 0; sy2[k] <= 0;
            end
        end else begin
            cf_start <= 1'b0;
            rd_start <= 1'b0;
            wr_start <= 1'b0;
            cw_start <= 1'b0;

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
                            state <= S_MODO_RD;
                        end else begin
                            c_idx <= c_idx + 1'b1;
                            state <= S_COEF_RD;
                        end
                    end
                end

                // ---- modo: estado zero (o de sempre) ou carregado ----
                S_MODO_RD: begin
                    cf_addr  <= EST_MODO;
                    cf_start <= 1'b1;
                    state    <= S_MODO_WAIT;
                end

                S_MODO_WAIT: begin
                    if (cf_done) begin
                        e_idx <= 0;
                        // if, e nao ?: -- uma SRAM nunca escrita le X na
                        // simulacao, e o if trata X como falso (modo 0)
                        if (cf_data[0]) state <= S_EST_RD;
                        else            state <= S_READ;
                    end
                end

                // ---- carga do estado inicial: 4 palavras por secao ----
                S_EST_RD: begin
                    cf_addr  <= EST_IN + e_idx;
                    cf_start <= 1'b1;
                    state    <= S_EST_WAIT;
                end

                S_EST_WAIT: begin
                    if (cf_done) begin
                        case (e_qual)
                            2'd0: sx1[e_sec] <= cf_data;
                            2'd1: sx2[e_sec] <= cf_data;
                            2'd2: sy1[e_sec] <= cf_data;
                            2'd3: sy2[e_sec] <= cf_data;
                        endcase
                        if (e_idx == n_est - 1) begin
                            e_idx <= 0;
                            state <= S_READ;
                        end else begin
                            e_idx <= e_idx + 1'b1;
                            state <= S_EST_RD;
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
                        state   <= S_SEL;
                    end
                end

                // Ciclo 1 da secao: copia estado e coeficientes de [s].
                // A amostra que entra ja esta em 'amostra' (x[n] na primeira
                // secao, y da secao anterior nas seguintes).
                S_SEL: begin
                    op_x1 <= sx1[s];  op_x2 <= sx2[s];
                    op_y1 <= sy1[s];  op_y2 <= sy2[s];
                    op_b0 <= cb0[s];  op_b1 <= cb1[s];  op_b2 <= cb2[s];
                    op_a1 <= ca1[s];  op_a2 <= ca2[s];
                    state <= S_MAC;
                end

                // Ciclo 2 da secao: yn e combinacional sobre os op_*. A
                // saida de uma secao vira a entrada da proxima na mesma
                // amostra -- e o que faz a cascata ser uma passagem so.
                S_MAC: begin
                    if (estourou) error_sat <= 1'b1;
                    sx2[s] <= op_x1;  sx1[s] <= amostra;
                    sy2[s] <= op_y1;  sy1[s] <= yn;
                    amostra <= yn;
                    if (s == n_secoes - 1) begin
                        wr_data <= yn;
                        state   <= S_WRITE;
                    end else begin
                        s     <= s + 1'b1;
                        state <= S_SEL;
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
                            e_idx <= 0;
                            state <= S_EST_WR;
                        end else begin
                            n     <= n + 1'b1;
                            state <= S_READ;
                        end
                    end
                end

                // ---- estado final, e por ultimo a marca ----
                // O dado e escolhido aqui e o controlador o pega um ciclo
                // depois (PREPARE_WRITE), ja estavel.
                S_EST_WR: begin
                    if (e_idx == n_est) begin
                        cw_addr <= EST_MARCA;
                        cw_data <= EST_MARCA_VALOR;
                    end else begin
                        cw_addr <= EST_OUT + e_idx;
                        case (e_qual)
                            2'd0: cw_data <= sx1[e_sec];
                            2'd1: cw_data <= sx2[e_sec];
                            2'd2: cw_data <= sy1[e_sec];
                            2'd3: cw_data <= sy2[e_sec];
                        endcase
                    end
                    cw_start <= 1'b1;
                    state    <= S_EST_WR_WAIT;
                end

                S_EST_WR_WAIT: begin
                    if (cw_done) begin
                        if (e_idx == n_est) begin
                            state <= S_DONE;
                        end else begin
                            e_idx <= e_idx + 1'b1;
                            state <= S_EST_WR;
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
    // A SRAM dos coeficientes tem um leitor e um escritor na mesma porta.
    // Nunca trabalham juntos (a FSM espera cada um terminar); o endereco
    // e do escritor enquanto ele esta ativo.
    wire [COEF_ADDR_N_BITS-1:0] cr_address, cw_address;
    wire cr_cs, cr_clken, cr_we, cw_cs, cw_clken, cw_we;

    memory_read_controller #(
        .DATA_WIDTH         (DATA_WIDTH),
        .MEM_ADDRESS_N_BITS (COEF_ADDR_N_BITS)
    ) u_rd_coef (
        .clk (clk), .reset_n (reset_n),
        .start_read    (cf_start),
        .sram_readdata (coef_sram_readdata),
        .data_addr     (cf_addr),
        .mem_write     (cr_we),
        .data_out      (cf_data),
        .mem_address   (cr_address),
        .read_done     (cf_done),
        .clken         (cr_clken),
        .chipselect    (cr_cs)
    );

    memory_write_controller #(
        .DATA_WIDTH         (DATA_WIDTH),
        .MEM_ADDRESS_N_BITS (COEF_ADDR_N_BITS)
    ) u_wr_coef (
        .clk (clk), .reset_n (reset_n),
        .start_write  (cw_start),
        .data_in_addr (cw_addr),
        .data_in      (cw_data),
        .write_done   (cw_done),
        .mem_address  (cw_address),
        .mem_wdata    (coef_sram_wdata),
        .mem_write    (cw_we),
        .clken        (cw_clken),
        .chipselect   (cw_cs)
    );

    assign coef_sram_address    = (cw_cs | cw_we) ? cw_address : cr_address;
    assign coef_sram_chipselect = cr_cs | cw_cs;
    assign coef_sram_clken      = cr_clken | cw_clken;
    assign coef_sram_write      = cr_we | cw_we;

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
