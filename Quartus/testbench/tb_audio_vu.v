// tb_audio_vu.v -- testbench do medidor de nivel (audio_vu.v).
//
// Confere: silencio = degrau 0 e displays apagados; pico de +-1000 (bit 9) =
// degrau 9; -32768 = degrau 15 e os 15 segmentos acesos; o degrau cai depois
// do pico (decaimento) e nao fica preso.
//
// Rodar (de Quartus/):
//   iverilog -g2012 -o tb_vu testbench/tb_audio_vu.v audio_vu.v
//   vvp tb_vu
`timescale 1ns/1ps

module tb_audio_vu;

reg clk = 0;
always #10 clk = ~clk;
reg reset_n = 0;
reg [15:0] esq = 0, dir = 0;
reg quadro = 0;
wire [6:0] h0, h1, h2, h3, h4;
wire [3:0] degrau;
integer erros = 0;

audio_vu dut (.clk(clk), .reset_n(reset_n), .esq(esq), .dir(dir), .quadro(quadro),
              .hex0(h0), .hex1(h1), .hex2(h2), .hex3(h3), .hex4(h4), .degrau(degrau));

task quadros(input integer n, input [15:0] e, input [15:0] d);
    integer i;
    for (i = 0; i < n; i = i + 1) begin
        @(negedge clk); esq = e; dir = d; quadro = 1;
        @(negedge clk); quadro = 0;
        repeat (3) @(negedge clk);
    end
endtask

task confere(input [3:0] esperado, input [255:0] nome);
    if (degrau !== esperado) begin
        erros = erros + 1;
        $display("ERRO %0s: degrau %0d (esperado %0d)", nome, degrau, esperado);
    end else
        $display("ok   %0s: degrau %0d", nome, degrau);
endtask

integer acesos;
initial begin
    #100 reset_n = 1;
    quadros(10, 0, 0);
    confere(0, "silencio");
    if ({h4, h3, h2, h1, h0} !== {35{1'b1}}) begin erros = erros + 1; $display("ERRO displays acesos no silencio"); end

    quadros(1, 16'd1000, 16'd3);          // 1000 = bit 9
    confere(9, "pico de 1000 no esquerdo");
    quadros(1, 16'd0, -16'sd1000);
    confere(9, "pico de -1000 no direito");

    quadros(1, 16'h8000, 0);              // -32768
    confere(15, "-32768");
    acesos = 0;
    for (integer k = 0; k < 7; k = k + 1)
        acesos = acesos + !h0[k] + !h1[k] + !h2[k] + !h3[k] + !h4[k];
    if (acesos != 15) begin erros = erros + 1; $display("ERRO %0d segmentos acesos no fundo de escala (esperado 15)", acesos); end
    else $display("ok   15 segmentos acesos no fundo de escala");

    // ~0,5 s de silencio (3 constantes de tempo): o nivel cai ~20x, uns 4 degraus
    quadros(24000, 0, 0);
    if (degrau >= 15 || degrau < 9) begin
        erros = erros + 1;
        $display("ERRO decaimento: degrau %0d depois de 0,5 s (esperado entre 9 e 14)", degrau);
    end else
        $display("ok   decaimento: degrau %0d depois de 0,5 s", degrau);

    if (erros == 0) $display("TUDO OK: medidor de nivel");
    else            $display("FALHOU: %0d erro(s)", erros);
    $finish;
end

endmodule
