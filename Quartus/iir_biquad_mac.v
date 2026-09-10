// =============================================================================
// iir_biquad_mac.v -- o caminho de dados de um biquad, combinacional.
//
// Uma amostra entra, uma sai. Sem estado, sem relogio: quem guarda x[n-1],
// x[n-2], y[n-1] e y[n-2] e quem instancia.
//
//     y[n] = b0*x[n] + b1*x[n-1] + b2*x[n-2] - a1*y[n-1] - a2*y[n-2]
//
// Existe como modulo separado por um motivo especifico: o iir_sos.v (uma
// secao) e o iir_cascade.v (varias) precisam arredondar e saturar EXATAMENTE
// igual. Duplicar essas quinze linhas nos dois seria criar duas verdades que
// divergem na primeira vez que alguem mexer numa delas -- e num filtro
// realimentado, divergir um LSB uma vez e divergir para sempre.
//
// Q15.16 nas amostras e nos coeficientes. a0 = 1 e implicito: o projetista
// normaliza cada secao antes de mandar.
//
//   produto  = Q15.16 * Q15.16 = Q31.32, 64 bits
//   5 produtos somados          -> +3 bits de guarda
//   ACC_WIDTH = 72 cobre com folga
//
// Arredondamento: soma meio LSB e desloca. Como o deslocamento e ARITMETICO,
// floor((acc + 2^15) / 2^16) arredonda meio para cima tambem nos negativos --
// o mesmo criterio do modelo em Python (iir_design.filtra_sos_fixo), o que e
// o que torna a comparacao bit a bit possivel.
//
// Saturacao, nunca wrap. Num laco realimentado o wrap-around leva de +max a
// -max e o filtro nunca mais se recupera; saturar degrada, mas nao destroi.
// =============================================================================

`timescale 1 ns / 1 ps

module iir_biquad_mac #(
    parameter DATA_WIDTH = 32,
    parameter FRAC_BITS  = 16,
    parameter ACC_WIDTH  = 72
)(
    input  wire signed [DATA_WIDTH-1:0] xn,
    input  wire signed [DATA_WIDTH-1:0] x1,
    input  wire signed [DATA_WIDTH-1:0] x2,
    input  wire signed [DATA_WIDTH-1:0] y1,
    input  wire signed [DATA_WIDTH-1:0] y2,

    input  wire signed [DATA_WIDTH-1:0] b0,
    input  wire signed [DATA_WIDTH-1:0] b1,
    input  wire signed [DATA_WIDTH-1:0] b2,
    input  wire signed [DATA_WIDTH-1:0] a1,
    input  wire signed [DATA_WIDTH-1:0] a2,

    output wire signed [DATA_WIDTH-1:0] yn,
    output wire                         saturou
);

    // Cada produto vira um bloco DSP do Cyclone V.
    wire signed [ACC_WIDTH-1:0] p_b0 = $signed(b0) * $signed(xn);
    wire signed [ACC_WIDTH-1:0] p_b1 = $signed(b1) * $signed(x1);
    wire signed [ACC_WIDTH-1:0] p_b2 = $signed(b2) * $signed(x2);
    wire signed [ACC_WIDTH-1:0] p_a1 = $signed(a1) * $signed(y1);
    wire signed [ACC_WIDTH-1:0] p_a2 = $signed(a2) * $signed(y2);

    wire signed [ACC_WIDTH-1:0] acc = p_b0 + p_b1 + p_b2 - p_a1 - p_a2;

    wire signed [ACC_WIDTH-1:0] acc_rnd =
        (acc + (1 <<< (FRAC_BITS - 1))) >>> FRAC_BITS;

    localparam signed [ACC_WIDTH-1:0] MAX_POS = (1 <<< (DATA_WIDTH - 1)) - 1;
    localparam signed [ACC_WIDTH-1:0] MIN_NEG = -(1 <<< (DATA_WIDTH - 1));

    assign saturou = (acc_rnd > MAX_POS) || (acc_rnd < MIN_NEG);
    assign yn = (acc_rnd > MAX_POS) ? MAX_POS[DATA_WIDTH-1:0] :
                (acc_rnd < MIN_NEG) ? MIN_NEG[DATA_WIDTH-1:0] :
                                      acc_rnd[DATA_WIDTH-1:0];

endmodule
