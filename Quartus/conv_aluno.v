// =============================================================================
// conv_aluno.v -- a convolucao discreta que VOCE escreve:
//
//     y[n] = soma, para k de 0 a nx-1, de x[k] * h[n-k]      n = 0 .. nx+nh-2
//
// Roteiro: docs/roteiro-conv/ (Parte A). Tudo em volta deste modulo ja esta
// pronto: as memorias de x, h e y, os PIOs de start/done/tamanhos, as
// ligacoes no ghrd_top.v, o servidor C (opcode CONV_ALUNO) e a janela do
// aplicativo que compara o seu resultado com o da convolucao do Morphe
// (conv1d.v). Aqui so estao as ENTRADAS e as SAIDAS; o corpo e com voce.
//
// Formato: Q15.16 com sinal, como todo o Morphe (valor = inteiro / 65536).
// Para o resultado bater BIT A BIT com o conv1d, faca a conta do mesmo jeito:
//   - produto x[k]*h[n-k] em 64 bits;
//   - de cada produto, fique com os bits [47:16] (volta a Q15.16);
//   - some esses valores num acumulador de 32 bits, sem saturar.
//
// Memorias (porta s1 das RAMs do Platform Designer, ja ligadas no topo):
//   - leitura de x e h: ponha o endereco em x_addr/h_addr; o dado aparece em
//     x_data/h_data UM ciclo depois de o endereco estar no fio. Se x_addr e
//     um reg atribuido num estado, o dado so pode ser usado DOIS estados
//     depois (um estado de espera no meio);
//   - escrita de y: no ciclo em que y_we = 1, a memoria grava y_data no
//     endereco y_addr, na borda do relogio.
//
// Protocolo de start/done (o mesmo da soma, do IIR e do conv1d):
//   1. o HPS escreve x, h, nx e nh e poe start = 1 (a BORDA de subida dispara);
//   2. o modulo calcula as nx+nh-1 amostras de y e entao poe done = 1;
//   3. o HPS le y e poe start = 0; com start em 0, done volta a 0.
// =============================================================================

`timescale 1 ns / 1 ps

module conv_aluno #(
    parameter DATA_WIDTH  = 32,
    parameter X_ADDR_BITS = 10,     // x: ate 1024 amostras
    parameter H_ADDR_BITS = 10,     // h: ate 1024 amostras
    parameter Y_ADDR_BITS = 11      // y: ate 2047 amostras (nx + nh - 1)
)(
    input  wire                          clk,       // 50 MHz
    input  wire                          reset_n,   // ativo em 0

    // --- controle (PIOs) ---
    input  wire                          start,     // HPS -> FPGA
    output reg                           done,      // FPGA -> HPS
    input  wire [X_ADDR_BITS:0]          nx,        // amostras de x, 1 a 1024
    input  wire [H_ADDR_BITS:0]          nh,        // amostras de h, 1 a 1024

    // --- memoria de x[k] (so leitura) ---
    output reg  [X_ADDR_BITS-1:0]        x_addr,
    input  wire signed [DATA_WIDTH-1:0]  x_data,

    // --- memoria de h[k] (so leitura) ---
    output reg  [H_ADDR_BITS-1:0]        h_addr,
    input  wire signed [DATA_WIDTH-1:0]  h_data,

    // --- memoria de y[n] (so escrita) ---
    output reg  [Y_ADDR_BITS-1:0]        y_addr,
    output reg  signed [DATA_WIDTH-1:0]  y_data,
    output reg                           y_we
);

    // ------------------------------------------------------------------
    // Escreva aqui a sua convolucao.
    // ------------------------------------------------------------------

endmodule
