// tb_filtro_audio.v -- testbench do filtro_audio.v contra o modelo em Python.
//
// Le os vetores do gera_vetores_filtro_audio.py (fa_coef.hex, fa_x.hex,
// fa_y.hex), carrega os coeficientes pela porta coef_*, entrega uma amostra a
// cada 64 ciclos (o hardware tem 1024; 64 ja e mais que as 16 secoes x 2) e
// confere a saida bit a bit: y_out e x_out da amostra n ficam prontos antes da
// amostra n+1.
//
// Rodar: Quartus/testbench/roda_tb_filtro_audio.sh (gera os vetores e roda
// todos os casos). Os defines NSEC e NAMOSTRAS vem de fa_n.txt.
`timescale 1ns/1ps

`ifndef NSEC
`define NSEC 4
`endif
`ifndef NAMOSTRAS
`define NAMOSTRAS 2000
`endif

module tb_filtro_audio;

localparam NS = `NSEC;
localparam NA = `NAMOSTRAS;

reg clk = 0;
always #10 clk = ~clk;
reg reset_n = 0;

reg               quadro = 0;
reg signed [15:0] x_in = 0;
reg               coef_we = 0;
reg [3:0]         coef_sec = 0;
reg [2:0]         coef_k = 0;
reg signed [31:0] coef_dado = 0;
wire signed [15:0] y_out, x_out;
wire               saturou;

filtro_audio dut (
    .clk(clk), .reset_n(reset_n), .quadro(quadro), .x_in(x_in),
    .n_secoes(NS[4:0]),
    .coef_we(coef_we), .coef_sec(coef_sec), .coef_k(coef_k), .coef_dado(coef_dado),
    .y_out(y_out), .x_out(x_out), .saturou(saturou)
);

reg [31:0] mem_c [0:5*16];
reg [15:0] mem_x [0:NA-1];
reg [15:0] mem_y [0:NA-1];
integer i, erros = 0;

initial begin
    $readmemh("fa_coef.hex", mem_c);
    $readmemh("fa_x.hex", mem_x);
    $readmemh("fa_y.hex", mem_y);
    #100 reset_n = 1;
    // carga dos coeficientes, como o audio_buf.v faz
    for (i = 0; i < 5 * NS; i = i + 1) begin
        @(negedge clk);
        coef_sec = i / 5; coef_k = i % 5; coef_dado = mem_c[i]; coef_we = 1;
        @(negedge clk);
        coef_we = 0;
    end
    repeat (5) @(negedge clk);
    for (i = 0; i < NA; i = i + 1) begin
        @(negedge clk);
        x_in = mem_x[i]; quadro = 1;
        @(negedge clk);
        quadro = 0;
        repeat (62) @(negedge clk);
        if (y_out !== mem_y[i] || x_out !== mem_x[i]) begin
            erros = erros + 1;
            if (erros < 8)
                $display("ERRO amostra %0d: y %0d (modelo %0d), x %0d (entrou %0d)",
                         i, y_out, $signed(mem_y[i]), x_out, $signed(mem_x[i]));
        end
    end
    if (erros == 0)
        $display("TUDO OK: %0d secoes, %0d amostras bit a bit iguais ao modelo%s",
                 NS, NA, saturou ? " (com saturacao interna)" : "");
    else
        $display("FALHOU: %0d de %0d amostras diferentes", erros, NA);
    $finish;
end

endmodule
