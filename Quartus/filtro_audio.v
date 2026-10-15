// =============================================================================
// filtro_audio.v -- filtro IIR em tempo real no caminho do audio do codec.
//
// Uma cascata de ate MAX_SECOES biquads (Forma Direta I, Q15.16), a MESMA
// aritmetica do iir_cascade.v: o caminho de dados e o iir_biquad_mac.v, que
// arredonda e satura igual ao modelo em Python (iir_design.filtra_sos_fixo).
// A diferenca e o ritmo: o iir_cascade processa um bloco da memoria e para;
// este processa cada amostra assim que ela chega do codec, para sempre, e os
// estados de uma amostra passam para a seguinte -- e um filtro de verdade,
// que se ouve.
//
// Tempo: chega uma amostra a cada 1024 ciclos de 50 MHz (fs = 48 828 Hz), e
// a cascata gasta 2 ciclos por secao (S_SEL copia os operandos da secao s
// para registradores, S_CALC calcula; o mesmo estagio que fez o iir_cascade
// fechar a 60 MHz) -- 16 secoes levam 35 ciclos. Sobra muito.
//
// Formatos: a amostra do codec e int16, x/32768 em [-1, 1). Em Q15.16 isso e
// x * 2 (1,0 = 65536), exato. Na saida, y Q15.16 volta a int16 por
// floor(y/2 + 1/2), saturado em [-32768, 32767]. O modelo de referencia e
// filtra_sos_fixo(x/32768, sos, 16, 32), seguido dessa conversao.
//
// Coeficientes: 5 por secao (b0 b1 b2 a1 a2, a0 = 1), Q15.16, escritos um a
// um pela porta coef_* (quem le a RAM e o audio_buf.v). Escrever coeficientes
// zera os estados. n_secoes = 0: passa a amostra direto (y = x).
//
// A saida de uma amostra fica pronta muito antes da proxima; quem usa
// (audio_buf.v) pega y_out e x_out no pulso seguinte -- um quadro de atraso,
// 20 us, com o par (entrada, saida) sempre alinhado.
// =============================================================================

`timescale 1 ns / 1 ps

module filtro_audio #(
    parameter MAX_SECOES = 16
) (
    input  wire               clk,
    input  wire               reset_n,

    input  wire               quadro,       // 1 ciclo: x_in e uma amostra nova
    input  wire signed [15:0] x_in,
    input  wire [4:0]         n_secoes,     // 0 = passa direto

    input  wire               coef_we,
    input  wire [3:0]         coef_sec,
    input  wire [2:0]         coef_k,       // 0 b0, 1 b1, 2 b2, 3 a1, 4 a2
    input  wire signed [31:0] coef_dado,

    output reg  signed [15:0] y_out,        // saida da ultima amostra filtrada
    output reg  signed [15:0] x_out,        // a entrada correspondente
    output reg                saturou       // alguma secao saturou (fica ate a carga)
);

localparam S_IDLE = 2'd0, S_SEL = 2'd1, S_CALC = 2'd2, S_OUT = 2'd3;

reg signed [31:0] cb0 [0:MAX_SECOES-1];
reg signed [31:0] cb1 [0:MAX_SECOES-1];
reg signed [31:0] cb2 [0:MAX_SECOES-1];
reg signed [31:0] ca1 [0:MAX_SECOES-1];
reg signed [31:0] ca2 [0:MAX_SECOES-1];
reg signed [31:0] sx1 [0:MAX_SECOES-1];
reg signed [31:0] sx2 [0:MAX_SECOES-1];
reg signed [31:0] sy1 [0:MAX_SECOES-1];
reg signed [31:0] sy2 [0:MAX_SECOES-1];

reg [1:0]  estado;
reg [3:0]  s;
reg [4:0]  n_r;
reg signed [31:0] amostra;
reg signed [15:0] x_lat;
reg signed [31:0] op_x1, op_x2, op_y1, op_y2;
reg signed [31:0] op_b0, op_b1, op_b2, op_a1, op_a2;

wire signed [31:0] yn;
wire               estourou;

iir_biquad_mac #(
    .DATA_WIDTH (32),
    .FRAC_BITS  (16),
    .ACC_WIDTH  (72)
) u_mac (
    .xn (amostra),
    .x1 (op_x1), .x2 (op_x2),
    .y1 (op_y1), .y2 (op_y2),
    .b0 (op_b0), .b1 (op_b1), .b2 (op_b2),
    .a1 (op_a1), .a2 (op_a2),
    .yn (yn), .saturou (estourou)
);

// Q15.16 -> int16: floor(y/2 + 1/2), saturado
wire signed [32:0] y_meio = ($signed({amostra[31], amostra}) + 33'sd1) >>> 1;
wire signed [15:0] y16 = (y_meio >  33'sd32767) ? 16'sd32767 :
                         (y_meio < -33'sd32768) ? -16'sd32768 :
                                                  y_meio[15:0];

integer k;

always @(posedge clk or negedge reset_n)
    if (!reset_n) begin
        estado  <= S_IDLE;
        s       <= 4'd0;
        n_r     <= 5'd0;
        amostra <= 32'sd0;
        x_lat   <= 16'sd0;
        y_out   <= 16'sd0;
        x_out   <= 16'sd0;
        saturou <= 1'b0;
        op_x1 <= 0; op_x2 <= 0; op_y1 <= 0; op_y2 <= 0;
        op_b0 <= 0; op_b1 <= 0; op_b2 <= 0; op_a1 <= 0; op_a2 <= 0;
        for (k = 0; k < MAX_SECOES; k = k + 1) begin
            cb0[k] <= 0; cb1[k] <= 0; cb2[k] <= 0; ca1[k] <= 0; ca2[k] <= 0;
            sx1[k] <= 0; sx2[k] <= 0; sy1[k] <= 0; sy2[k] <= 0;
        end
    end else if (coef_we) begin
        // carga de um coeficiente: os estados recomecam do zero, como no
        // iir_cascade, para que o mesmo sinal de sempre a mesma saida
        case (coef_k)
            3'd0: cb0[coef_sec] <= coef_dado;
            3'd1: cb1[coef_sec] <= coef_dado;
            3'd2: cb2[coef_sec] <= coef_dado;
            3'd3: ca1[coef_sec] <= coef_dado;
            default: ca2[coef_sec] <= coef_dado;
        endcase
        for (k = 0; k < MAX_SECOES; k = k + 1) begin
            sx1[k] <= 0; sx2[k] <= 0; sy1[k] <= 0; sy2[k] <= 0;
        end
        saturou <= 1'b0;
        estado  <= S_IDLE;
    end else begin
        case (estado)
        S_IDLE:
            if (quadro) begin
                x_lat   <= x_in;
                amostra <= {{15{x_in[15]}}, x_in, 1'b0};     // x * 2: Q15.16
                n_r     <= n_secoes;
                s       <= 4'd0;
                estado  <= (n_secoes == 5'd0) ? S_OUT : S_SEL;
            end

        S_SEL: begin
            op_x1 <= sx1[s]; op_x2 <= sx2[s];
            op_y1 <= sy1[s]; op_y2 <= sy2[s];
            op_b0 <= cb0[s]; op_b1 <= cb1[s]; op_b2 <= cb2[s];
            op_a1 <= ca1[s]; op_a2 <= ca2[s];
            estado <= S_CALC;
        end

        S_CALC: begin
            sx2[s]  <= sx1[s];
            sx1[s]  <= amostra;
            sy2[s]  <= sy1[s];
            sy1[s]  <= yn;
            amostra <= yn;
            if (estourou) saturou <= 1'b1;
            if ({1'b0, s} == n_r - 5'd1) begin
                estado <= S_OUT;
            end else begin
                s      <= s + 4'd1;
                estado <= S_SEL;
            end
        end

        S_OUT: begin
            y_out  <= y16;
            x_out  <= x_lat;
            estado <= S_IDLE;
        end
        endcase
    end

endmodule
