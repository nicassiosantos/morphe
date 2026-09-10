// =============================================================================
// iir_sos.v -- uma secao de 2a ordem (biquad) IIR em Q15.16.
//
// Passo 1 do bloco IIR. Processa N amostras de uma SRAM para outra, com os
// cinco coeficientes vindo de fora como registradores -- a cascata de varias
// secoes e o passo 2, e vai reusar este modulo.
//
// FORMA DIRETA I, e a escolha nao e de estilo:
//
//     y[n] = b0*x[n] + b1*x[n-1] + b2*x[n-2] - a1*y[n-1] - a2*y[n-2]
//
// A DF-II transposta usa menos registradores e e a melhor em ponto
// FLUTUANTE, mas guarda estados ja truncados. Em ponto fixo a DF-I ganha
// porque a soma inteira acontece num acumulador unico e largo, e o
// arredondamento acontece uma vez so, na saida. Com realimentacao isso
// importa: erro truncado que volta para a entrada nao morre.
//
// Formato: amostras e coeficientes em Q15.16 (32 bits, 16 fracionarios).
// a0 = 1 e implicito -- o projetista normaliza cada secao antes de mandar.
//
//   produto  = Q15.16 * Q15.16 = Q31.32, 64 bits
//   soma de 5 produtos             -> +3 bits de guarda
//   ACC_WIDTH = 72 cobre com folga
//
// Volta para Q15.16 com arredondamento (soma meio LSB e desloca) e SATURA
// em vez de dar wrap. Wrap num laco realimentado vira oscilacao sustentada:
// o valor pula de +max para -max e o filtro nunca mais se recupera.
//
// error_sat fica em 1 (sticky ate o proximo start) se qualquer amostra
// saturou. E informacao que o aluno precisa: significa que o ganho do
// filtro estourou a faixa, nao que o filtro esta errado.
//
// Dead band: com entrada em silencio a saida pode travar num valor
// constante em vez de ir a zero. Isso NAO e defeito deste modulo -- e
// propriedade de qualquer IIR em ponto fixo, e o cliente ja mede e avisa
// antes de mandar (ver Python/iir_design.py, verifica_viabilidade).
// =============================================================================

`timescale 1 ns / 1 ps

module iir_sos #(
    parameter DATA_WIDTH    = 32,
    parameter FRAC_BITS     = 16,
    parameter ACC_WIDTH     = 72,
    parameter N_SAMPLES     = 1024,
    parameter ADDR_N_BITS   = 10
)(
    input  wire                         clk,
    input  wire                         reset_n,
    input  wire                         start,      // pulso do HPS
    output reg                          done,
    output reg                          error_sat,  // saturou em alguma amostra

    // --- Coeficientes, Q15.16. a0 = 1 implicito ---
    input  wire signed [DATA_WIDTH-1:0] b0,
    input  wire signed [DATA_WIDTH-1:0] b1,
    input  wire signed [DATA_WIDTH-1:0] b2,
    input  wire signed [DATA_WIDTH-1:0] a1,
    input  wire signed [DATA_WIDTH-1:0] a2,

    // --- SRAM de entrada x[n] ---
    input  wire [DATA_WIDTH-1:0]        xn_sram_readdata,
    output wire [ADDR_N_BITS-1:0]       xn_sram_address,
    output wire                         xn_sram_chipselect,
    output wire                         xn_sram_clken,
    output wire                         xn_sram_write,

    // --- SRAM de saida y[n] ---
    output wire [ADDR_N_BITS-1:0]       yn_sram_address,
    output wire [DATA_WIDTH-1:0]        yn_sram_wdata,
    output wire                         yn_sram_chipselect,
    output wire                         yn_sram_clken,
    output wire                         yn_sram_write,

    output wire [2:0]                   debug_state
);

    // --- Estados ---
    localparam [2:0] S_IDLE       = 3'd0;
    localparam [2:0] S_READ       = 3'd1;
    localparam [2:0] S_WAIT_READ  = 3'd2;
    localparam [2:0] S_MAC        = 3'd3;  // multiplica e acumula
    localparam [2:0] S_WRITE      = 3'd4;
    localparam [2:0] S_WAIT_WRITE = 3'd5;
    localparam [2:0] S_DONE       = 3'd6;

    reg [2:0] state;
    assign debug_state = state;

    reg [ADDR_N_BITS-1:0] n;      // indice da amostra

    // --- Detector de borda do start (mesma convencao do conv1d) ---
    reg start_d;
    wire start_pulse = start & ~start_d;
    always @(posedge clk or negedge reset_n) begin
        if (!reset_n) start_d <= 1'b0;
        else          start_d <= start;
    end

    // --- Estados do filtro: as quatro memorias da Forma Direta I ---
    reg signed [DATA_WIDTH-1:0] x1, x2;   // x[n-1], x[n-2]
    reg signed [DATA_WIDTH-1:0] y1, y2;   // y[n-1], y[n-2]
    reg signed [DATA_WIDTH-1:0] xn;       // amostra corrente

    // --- Controle das memorias ---
    reg                          rd_start;
    reg  [ADDR_N_BITS-1:0]       rd_addr;
    wire [DATA_WIDTH-1:0]        rd_data;
    wire                         rd_done;

    reg                          wr_start;
    reg  [ADDR_N_BITS-1:0]       wr_addr;
    reg  [DATA_WIDTH-1:0]        wr_data;
    wire                         wr_done;

    // --- Caminho de dados ---
    // Os cinco produtos, cada um Q31.32 em ACC_WIDTH bits com extensao de
    // sinal. O sintetizador mapeia cada um num bloco DSP do Cyclone V.
    wire signed [ACC_WIDTH-1:0] p_b0 = $signed(b0) * $signed(xn);
    wire signed [ACC_WIDTH-1:0] p_b1 = $signed(b1) * $signed(x1);
    wire signed [ACC_WIDTH-1:0] p_b2 = $signed(b2) * $signed(x2);
    wire signed [ACC_WIDTH-1:0] p_a1 = $signed(a1) * $signed(y1);
    wire signed [ACC_WIDTH-1:0] p_a2 = $signed(a2) * $signed(y2);

    wire signed [ACC_WIDTH-1:0] acc = p_b0 + p_b1 + p_b2 - p_a1 - p_a2;

    // Volta para Q15.16: soma meio LSB e desloca. Como e deslocamento
    // ARITMETICO, floor((acc + 2^15) / 2^16) arredonda meio para cima
    // tambem nos negativos -- o mesmo criterio do modelo em Python, o que
    // deixa a comparacao bit a bit possivel.
    wire signed [ACC_WIDTH-1:0] acc_rnd =
        (acc + (1 <<< (FRAC_BITS - 1))) >>> FRAC_BITS;

    // Saturacao. Nunca wrap: ver o cabecalho.
    localparam signed [ACC_WIDTH-1:0] MAX_POS =
        (1 <<< (DATA_WIDTH - 1)) - 1;
    localparam signed [ACC_WIDTH-1:0] MIN_NEG =
        -(1 <<< (DATA_WIDTH - 1));

    wire estourou = (acc_rnd > MAX_POS) || (acc_rnd < MIN_NEG);
    wire signed [DATA_WIDTH-1:0] yn =
        (acc_rnd > MAX_POS) ? MAX_POS[DATA_WIDTH-1:0] :
        (acc_rnd < MIN_NEG) ? MIN_NEG[DATA_WIDTH-1:0] :
                              acc_rnd[DATA_WIDTH-1:0];

    // --- FSM ---
    always @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            state     <= S_IDLE;
            done      <= 1'b0;
            error_sat <= 1'b0;
            n         <= {ADDR_N_BITS{1'b0}};
            x1 <= 0; x2 <= 0; y1 <= 0; y2 <= 0; xn <= 0;
            rd_start  <= 1'b0;
            wr_start  <= 1'b0;
            rd_addr   <= {ADDR_N_BITS{1'b0}};
            wr_addr   <= {ADDR_N_BITS{1'b0}};
            wr_data   <= {DATA_WIDTH{1'b0}};
        end else begin
            // pulsos de 1 ciclo
            rd_start <= 1'b0;
            wr_start <= 1'b0;

            case (state)
                S_IDLE: begin
                    done <= 1'b0;
                    if (start_pulse) begin
                        // Estado zerado a cada execucao: sem isto o
                        // resultado dependeria da rodada anterior.
                        n  <= 0;
                        x1 <= 0; x2 <= 0; y1 <= 0; y2 <= 0;
                        error_sat <= 1'b0;
                        state <= S_READ;
                    end
                end

                S_READ: begin
                    rd_addr  <= n;
                    rd_start <= 1'b1;
                    state    <= S_WAIT_READ;
                end

                S_WAIT_READ: begin
                    if (rd_done) begin
                        xn    <= rd_data;
                        state <= S_MAC;
                    end
                end

                S_MAC: begin
                    // acc/yn sao combinacionais sobre xn, x1, x2, y1, y2:
                    // aqui so registramos o resultado e giramos os estados.
                    wr_data <= yn;
                    if (estourou) error_sat <= 1'b1;
                    x2 <= x1;  x1 <= xn;
                    y2 <= y1;  y1 <= yn;
                    state <= S_WRITE;
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
                    if (!start) state <= S_IDLE;   // handshake com o HPS
                end

                default: state <= S_IDLE;
            endcase
        end
    end

    // --- Controladores de memoria, os mesmos do conv1d ---
    memory_read_controller #(
        .DATA_WIDTH         (DATA_WIDTH),
        .MEM_ADDRESS_N_BITS (ADDR_N_BITS)
    ) u_rd (
        .clk            (clk),
        .reset_n        (reset_n),
        .start_read     (rd_start),
        .sram_readdata  (xn_sram_readdata),
        .data_addr      (rd_addr),
        .mem_write      (xn_sram_write),
        .data_out       (rd_data),
        .mem_address    (xn_sram_address),
        .read_done      (rd_done),
        .clken          (xn_sram_clken),
        .chipselect     (xn_sram_chipselect)
    );

    memory_write_controller #(
        .DATA_WIDTH         (DATA_WIDTH),
        .MEM_ADDRESS_N_BITS (ADDR_N_BITS)
    ) u_wr (
        .clk            (clk),
        .reset_n        (reset_n),
        .start_write    (wr_start),
        .data_in_addr   (wr_addr),
        .data_in        (wr_data),
        .write_done     (wr_done),
        .mem_address    (yn_sram_address),
        .mem_wdata      (yn_sram_wdata),
        .mem_write      (yn_sram_write),
        .clken          (yn_sram_clken),
        .chipselect     (yn_sram_chipselect)
    );

endmodule
