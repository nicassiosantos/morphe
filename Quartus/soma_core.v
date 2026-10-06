// =============================================================================
// soma_core.v -- o nucleo da soma: y = a + b, um par de numeros por vez.
//
// E so a conta, sem memoria e sem controle. Por isso da para testar sozinho
// (roteiro, Parte A: tres PIOs ligados direto nele, lidos e escritos pela
// serial da placa) antes de entrar no soma.v, que o usa amostra a amostra.
//
// Formato: Q15.16 com sinal, como todo o Morphe (valor = inteiro / 65536).
// Somar dois Q15.16 da outro Q15.16 -- a virgula nao muda --, mas a soma pode
// passar de 32 bits. Em vez de deixar dar a volta (um positivo grande virar
// negativo), satura: a conta e feita em 33 bits e o resultado e limitado a
// faixa de 32 (de -32768 a +32767,99998).
//
// Combinacional: y muda junto com a e b, sem relogio.
// =============================================================================

`timescale 1 ns / 1 ps

module soma_core #(
    parameter DATA_WIDTH = 32
)(
    input  wire [DATA_WIDTH-1:0] a,
    input  wire [DATA_WIDTH-1:0] b,
    output wire [DATA_WIDTH-1:0] y
);

    // os limites de 32 bits com sinal, escritos em 33 bits
    localparam signed [DATA_WIDTH:0] MAXV = {2'b00, {(DATA_WIDTH-1){1'b1}}};  //  2^31 - 1
    localparam signed [DATA_WIDTH:0] MINV = {2'b11, {(DATA_WIDTH-1){1'b0}}};  // -2^31

    // estende o sinal para 33 bits e soma: aqui nao ha estouro
    wire signed [DATA_WIDTH:0] soma_larga =
        $signed({a[DATA_WIDTH-1], a}) + $signed({b[DATA_WIDTH-1], b});

    // volta para 32 bits, saturando
    assign y = (soma_larga > MAXV) ? MAXV[DATA_WIDTH-1:0] :
               (soma_larga < MINV) ? MINV[DATA_WIDTH-1:0] :
                                     soma_larga[DATA_WIDTH-1:0];

endmodule
