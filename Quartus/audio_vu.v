// =============================================================================
// audio_vu.v -- medidor de nivel do audio recebido do codec, nos displays HEX0..HEX4.
//
// Serve para ver a RECEPCAO I2S funcionando sem nenhum cabo de audio: com um
// fone no MIC-in (rosa) fazendo papel de microfone, bater nele ou falar perto
// acende os segmentos.
//
// Nivel: pico de max(|esq|, |dir|), atualizado a cada quadro, com decaimento
// exponencial (nivel -= nivel/8192 por quadro: constante de tempo de
// 8192 / 48 828 Hz = 0,17 s). A escala e LOGARITMICA -- 6 dB por degrau: o
// degrau e a posicao do bit mais significativo do nivel (1 a 15), porque um
// fone usado como microfone da um sinal muito fraco e numa escala linear so o
// primeiro segmento acenderia.
//
// Desenho: 15 degraus em 5 displays, 3 por display, da direita (HEX0) para a
// esquerda (HEX4): em cada display acende primeiro o segmento de baixo (d),
// depois o do meio (g), depois o de cima (a). Segmentos ativos em 0.
// =============================================================================

module audio_vu (
    input  wire        clk,
    input  wire        reset_n,
    input  wire [15:0] esq,         // complemento de dois
    input  wire [15:0] dir,
    input  wire        quadro,      // 1 ciclo por amostra estereo nova
    output wire [6:0]  hex0,
    output wire [6:0]  hex1,
    output wire [6:0]  hex2,
    output wire [6:0]  hex3,
    output wire [6:0]  hex4,
    output reg  [3:0]  degrau       // 0..15 (para o testbench)
);

// modulo de um valor de 16 bits em complemento de dois (-32768 -> 32768)
function [15:0] modulo;
    input [15:0] x;
    modulo = x[15] ? (~x + 16'd1) : x;
endfunction

wire [15:0] m_esq = modulo(esq);
wire [15:0] m_dir = modulo(dir);
wire [15:0] m     = (m_esq > m_dir) ? m_esq : m_dir;

// nivel com 13 bits de fracao, para o decaimento nao parar em valores pequenos
reg  [28:0] nivel;
wire [28:0] decaido  = nivel - (nivel >> 13);
wire [28:0] entrada  = {m, 13'd0};

always @(posedge clk or negedge reset_n)
    if (!reset_n)    nivel <= 29'd0;
    else if (quadro) nivel <= (entrada > decaido) ? entrada : decaido;

// degrau = posicao do bit mais significativo da parte inteira (0 se < 1)
wire [15:0] inteiro = nivel[28:13];
integer b;
always @(*) begin
    degrau = 4'd0;
    for (b = 1; b < 16; b = b + 1)
        if (inteiro[b]) degrau = b[3:0];
end

// segmentos de cada display: {g,f,e,d,c,b,a}, ativos em 0
function [6:0] segmentos;
    input [3:0] d;        // degrau
    input [3:0] base;     // degrau a partir do qual este display comeca
    begin
        segmentos = 7'b1111111;
        if (d >= base)         segmentos[3] = 1'b0;   // d (baixo)
        if (d >= base + 4'd1)  segmentos[6] = 1'b0;   // g (meio)
        if (d >= base + 4'd2)  segmentos[0] = 1'b0;   // a (cima)
    end
endfunction

assign hex0 = segmentos(degrau, 4'd1);
assign hex1 = segmentos(degrau, 4'd4);
assign hex2 = segmentos(degrau, 4'd7);
assign hex3 = segmentos(degrau, 4'd10);
assign hex4 = segmentos(degrau, 4'd13);

endmodule
