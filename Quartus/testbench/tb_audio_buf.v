// tb_audio_buf.v -- testbench do audio_buf.v (captura, reproducao e loopback).
//
// Entrega quadros estereo direto (sem I2S), um a cada 16 ciclos, com valores
// conhecidos, e uma RAM como a adc_buf (leitura com 1 ciclo de latencia).
// RAM pequena (ADDR_BITS = 6, 64 palavras) para o modo continuo dar a volta.
//
// Confere:
//   1. captura unica de 40 quadros: RAM[i] = {dir, esq} do quadro i, done,
//      contador = 40, saida em silencio;
//   2. reproducao unica de 30 palavras: a saida toca RAM[0..29] em ordem, um
//      quadro cada, depois silencio e done;
//   3. captura + loopback continua por 150 quadros (a RAM da a volta): a saida
//      repete a entrada, RAM[i mod 64] = quadro i, contador = 150;
//   4. loopback: a saida repete a entrada, a RAM nao e escrita, contador = 0;
//      ao baixar o start, silencio;
//   5. reproducao continua por 150 quadros: saida = RAM[i mod 64].
//
// Rodar (de Quartus/):
//   iverilog -g2012 -o tb_abuf testbench/tb_audio_buf.v audio_buf.v && vvp tb_abuf
`timescale 1ns/1ps

module tb_audio_buf;

localparam AB = 6;
localparam NR = 1 << AB;

reg clk = 0;
always #10 clk = ~clk;
reg reset_n = 0;

reg        start = 0;
reg [1:0]  op = 0;
reg        continuo = 0;
reg [15:0] n_amostras = 0;
wire       done;
wire [31:0] contador;

reg  [15:0] rx_esq = 0, rx_dir = 0;
reg         rx_quadro = 0;
wire [15:0] tx_esq, tx_dir;

wire [AB-1:0] ram_address;
wire [31:0]   ram_wdata;
wire          ram_write;
reg  [31:0]   ram [0:NR-1];
reg  [31:0]   ram_readdata;
always @(posedge clk) begin
    ram_readdata <= ram[ram_address];
    if (ram_write) ram[ram_address] <= ram_wdata;
end

audio_buf #(.ADDR_BITS(AB)) dut (
    .clk(clk), .reset_n(reset_n), .start(start), .done(done), .op(op),
    .continuo(continuo), .n_amostras(n_amostras), .contador(contador),
    .rx_esq(rx_esq), .rx_dir(rx_dir), .rx_quadro(rx_quadro),
    .tx_esq(tx_esq), .tx_dir(tx_dir),
    .ram_address(ram_address), .ram_wdata(ram_wdata), .ram_write(ram_write),
    .ram_readdata(ram_readdata)
);

// quadro q: esq = 1000 + 3q, dir = -(500 + 7q). Um pulso a cada 16 ciclos; a
// amostra muda 4 ciclos antes do pulso, como no audio_i2s.v.
integer q = 0;
function [15:0] esq_de; input integer k; esq_de = 1000 + 3 * k; endfunction
function [15:0] dir_de; input integer k; dir_de = -(500 + 7 * k); endfunction
integer fase = 0;
always @(posedge clk) if (reset_n) begin
    rx_quadro <= 1'b0;
    fase <= (fase + 1) % 16;
    if (fase == 11) begin rx_esq <= esq_de(q); rx_dir <= dir_de(q); end
    if (fase == 15) begin rx_quadro <= 1'b1; q <= q + 1; end
end

// a saida e lida no ciclo seguinte ao pulso (o audio_i2s.v a usa bem depois)
reg [15:0] saida_esq [0:4095];
reg [15:0] saida_dir [0:4095];
integer ns = 0;
reg pulso_d = 0;
always @(posedge clk) begin
    pulso_d <= rx_quadro;
    if (pulso_d && ns < 4096) begin
        saida_esq[ns] <= tx_esq; saida_dir[ns] <= tx_dir; ns <= ns + 1;
    end
end

integer erros = 0;
integer i, q0, n0, escritas;
always @(posedge clk) if (ram_write) escritas = escritas + 1;

task para;
    begin @(negedge clk); start = 0; repeat (40) @(negedge clk); end
endtask

initial begin
    for (i = 0; i < NR; i = i + 1) ram[i] = 32'hDEAD0000 + i;
    #100 reset_n = 1;
    repeat (50) @(negedge clk);

    // ---- 1. captura unica ---------------------------------------------------
    @(negedge clk); op = 0; continuo = 0; n_amostras = 40;
    @(posedge rx_quadro); repeat (4) @(negedge clk); start = 1;
    q0 = q;                     // o proximo pulso grava o quadro q0
    wait (done);
    @(negedge clk);
    if (contador !== 40) begin erros = erros + 1; $display("ERRO 1: contador %0d", contador); end
    for (i = 0; i < 40; i = i + 1)
        if (ram[i] !== {dir_de(q0 + i), esq_de(q0 + i)}) begin
            erros = erros + 1;
            if (erros < 6) $display("ERRO 1: RAM[%0d] = %h, esperado %h", i, ram[i], {dir_de(q0+i), esq_de(q0+i)});
        end
    if (tx_esq !== 0 || tx_dir !== 0) begin erros = erros + 1; $display("ERRO 1: saida nao e silencio"); end
    para;
    if (contador !== 0 || done !== 0) begin erros = erros + 1; $display("ERRO 1: nao voltou ao repouso"); end
    if (erros == 0) $display("1. captura unica: 40 quadros na RAM, em ordem");

    // ---- 2. reproducao unica -------------------------------------------------
    for (i = 0; i < NR; i = i + 1) ram[i] = {16'(16'h7000 + i), 16'(16'h1000 + i)};
    @(negedge clk); op = 1; continuo = 0; n_amostras = 30;
    @(posedge rx_quadro); repeat (4) @(negedge clk); start = 1;
    n0 = ns;                    // a saida do proximo pulso e RAM[0]
    wait (done);
    repeat (40) @(negedge clk);
    for (i = 0; i < 30; i = i + 1)
        if (saida_esq[n0 + i] !== 16'h1000 + i || saida_dir[n0 + i] !== 16'h7000 + i) begin
            erros = erros + 1;
            if (erros < 6) $display("ERRO 2: quadro %0d tocou %h %h", i, saida_esq[n0+i], saida_dir[n0+i]);
        end
    if (saida_esq[n0 + 30] !== 0) begin erros = erros + 1; $display("ERRO 2: nao silenciou depois do fim"); end
    para;
    if (erros == 0) $display("2. reproducao unica: 30 palavras tocadas em ordem, depois silencio");

    // ---- 3. captura + loopback continua --------------------------------------
    escritas = 0;
    @(negedge clk); op = 2; continuo = 1; n_amostras = 0;
    @(posedge rx_quadro); repeat (4) @(negedge clk); start = 1;
    q0 = q; n0 = ns;
    wait (contador == 150);
    @(negedge clk); start = 0;
    repeat (40) @(negedge clk);
    for (i = 150 - NR; i < 150; i = i + 1)
        if (ram[i % NR] !== {dir_de(q0 + i), esq_de(q0 + i)}) begin
            erros = erros + 1;
            if (erros < 6) $display("ERRO 3: RAM[%0d] = %h (quadro %0d)", i % NR, ram[i % NR], i);
        end
    for (i = 0; i < 150; i = i + 1)
        if (saida_esq[n0 + i] !== esq_de(q0 + i) || saida_dir[n0 + i] !== dir_de(q0 + i)) begin
            erros = erros + 1;
            if (erros < 6) $display("ERRO 3: loopback quadro %0d: %h %h", i, saida_esq[n0+i], saida_dir[n0+i]);
        end
    if (escritas != 150) begin erros = erros + 1; $display("ERRO 3: %0d escritas na RAM", escritas); end
    if (erros == 0) $display("3. captura + loopback continua: 150 quadros, a RAM deu a volta");

    // ---- 4. loopback -----------------------------------------------------------
    escritas = 0;
    @(negedge clk); op = 3; continuo = 0; n_amostras = 0;
    @(posedge rx_quadro); repeat (4) @(negedge clk); start = 1;
    q0 = q; n0 = ns;
    repeat (100 * 16) @(negedge clk);
    for (i = 0; i < 90; i = i + 1)
        if (saida_esq[n0 + i] !== esq_de(q0 + i) || saida_dir[n0 + i] !== dir_de(q0 + i)) begin
            erros = erros + 1;
            if (erros < 6) $display("ERRO 4: loopback quadro %0d", i);
        end
    if (escritas != 0 || contador !== 0) begin
        erros = erros + 1; $display("ERRO 4: %0d escritas, contador %0d", escritas, contador);
    end
    para;
    repeat (40) @(negedge clk);
    if (tx_esq !== 0) begin erros = erros + 1; $display("ERRO 4: nao silenciou ao parar"); end
    if (erros == 0) $display("4. loopback: a saida repete a entrada, sem tocar na RAM");

    // ---- 5. reproducao continua ------------------------------------------------
    for (i = 0; i < NR; i = i + 1) ram[i] = {16'(16'h5000 + i), 16'(16'h2000 + i)};
    @(negedge clk); op = 1; continuo = 1; n_amostras = 0;
    @(posedge rx_quadro); repeat (4) @(negedge clk); start = 1;
    n0 = ns;
    wait (contador == 150);
    @(negedge clk); start = 0;
    repeat (40) @(negedge clk);
    for (i = 0; i < 150; i = i + 1)
        if (saida_esq[n0 + i] !== 16'h2000 + (i % NR) || saida_dir[n0 + i] !== 16'h5000 + (i % NR)) begin
            erros = erros + 1;
            if (erros < 6) $display("ERRO 5: quadro %0d tocou %h", i, saida_esq[n0+i]);
        end
    if (erros == 0) $display("5. reproducao continua: 150 quadros, a RAM deu a volta");

    if (erros == 0) $display("TUDO OK: captura, reproducao e loopback");
    else            $display("FALHOU: %0d erro(s)", erros);
    $finish;
end

initial begin
    #5000000;
    $display("FALHOU: tempo esgotado");
    $finish;
end

endmodule
