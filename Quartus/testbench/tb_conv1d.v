// tb_conv1d.v -- testbench do conv1d.v (convolucao e FIR) contra a conta exata.
//
// Memorias x, h e y modeladas como as on-chip RAMs do Qsys (leitura registrada,
// 1 ciclo). Sinais aleatorios em Q16.16, na faixa de +-2,0, sem estouro.
//
// Confere, amostra a amostra, que
//     y[n] = floor( sum_k x[k] h[n-k] / 2^16 + 1/2 )
// com a soma EXATA em 64 bits -- ou seja, o arredondamento uma vez so, na saida.
// Mostra tambem o erro maximo contra a conta exata (deve ficar <= 0,5 LSB) e o
// que o truncamento antigo (cada produto cortado para Q16.16) daria nos mesmos
// sinais, para comparar.
//
// Rodar: Quartus/testbench/roda_tb_conv.sh (N = 16 e N = 1024, ~1 min). Ele
// usa copias dos memory_*_controller.v com 1'b0 no lugar de 1'b_0, que o
// Quartus aceita e o Icarus nao. Na mao, com essas copias: -DN=<tamanho>.
`timescale 1ns/1ps

`ifndef N
`define N 16
`endif

module tb_conv1d;

localparam N  = `N;
localparam NY = 2 * N - 1;
localparam AX = $clog2(N);
localparam AY = $clog2(NY);

reg clk = 0;
always #10 clk = ~clk;
reg reset_n = 0;
reg start = 0;
wire done;

reg  signed [31:0] mem_x [0:N-1];
reg  signed [31:0] mem_h [0:N-1];
reg  signed [31:0] mem_y [0:NY-1];
reg  [31:0] rd_x, rd_h;
wire [AX-1:0] ad_x, ad_h;
wire [AY-1:0] ad_y;
wire [31:0] wd_y;
wire we_y;

always @(posedge clk) begin
    rd_x <= mem_x[ad_x];
    rd_h <= mem_h[ad_h];
    if (we_y) mem_y[ad_y] <= wd_y;
end

conv1d #(.DATA_WIDTH(32), .XN_LENGTH(N), .HN_LENGTH(N), .YN_LENGTH(NY),
         .XN_ADDR_N_BITS(AX), .HN_ADDR_N_BITS(AX), .YN_ADDR_N_BITS(AY)) dut (
    .clk(clk), .reset_n(reset_n), .start(start), .done(done),
    .xn_sram_readdata(rd_x), .xn_sram_address(ad_x),
    .xn_sram_chipselect(), .xn_sram_clken(), .xn_sram_write(),
    .hn_sram_readdata(rd_h), .hn_sram_address(ad_h),
    .hn_sram_chipselect(), .hn_sram_clken(), .hn_sram_write(),
    .yn_sram_address(ad_y), .yn_sram_wdata(wd_y),
    .yn_sram_chipselect(), .yn_sram_clken(), .yn_sram_write(we_y)
);

integer i, n, k, erros;
reg signed [63:0] soma, p;
reg signed [31:0] y_trunc, esperado;
real exato, e_arred, e_trunc, max_arred, max_trunc;

initial begin
    for (i = 0; i < N; i = i + 1) begin
        mem_x[i] = $signed($random) % (32'sd1 << 17);   // +-2,0 em Q16.16
        mem_h[i] = $signed($random) % (32'sd1 << 17);
    end
    // casos de borda nas duas primeiras amostras: produtos com resto exato de
    // meio LSB, positivo e negativo (empate: tem de ir para cima nos dois)
    mem_x[0] = 32'sd1 << 15;  mem_h[0] = 32'sd1;   // +0,5 LSB -> +1
    mem_x[1] = -(32'sd1 << 15); mem_h[1] = 32'sd1;  // y[1] mistura; conferido igual

    #100 reset_n = 1;
    // start muda na DESCIDA: na subida haveria corrida com o detector de borda
    #100 @(negedge clk) start = 1;
    @(negedge clk) @(negedge clk) start = 0;
    wait (done);
    @(posedge clk);

    erros = 0; max_arred = 0; max_trunc = 0;
    for (n = 0; n < NY; n = n + 1) begin
        soma = 0; y_trunc = 0;
        for (k = 0; k < N; k = k + 1)
            if (n - k >= 0 && n - k < N) begin
                p = mem_x[k] * mem_h[n - k];
                soma = soma + p;
                y_trunc = y_trunc + p[47:16];          // o conv1d antigo
            end
        esperado = (soma + (64'sd1 <<< 15)) >>> 16;
        exato   = soma;  exato = exato / 65536.0;   // sem $itor: ele corta em 32 bits
        e_arred = $itor(mem_y[n]) - exato;  if (e_arred < 0) e_arred = -e_arred;
        e_trunc = $itor(y_trunc)  - exato;  if (e_trunc < 0) e_trunc = -e_trunc;
        if (e_arred > max_arred) max_arred = e_arred;
        if (e_trunc > max_trunc) max_trunc = e_trunc;
        if (mem_y[n] !== esperado) begin
            erros = erros + 1;
            if (erros < 10)
                $display("ERRO y[%0d] = %0d, esperado %0d (exato %f)", n, mem_y[n], esperado, exato);
        end
    end
    if (mem_y[0] !== 32'sd1) begin
        erros = erros + 1;
        $display("ERRO empate: y[0] = %0d, esperado 1 (0,5 LSB arredonda para cima)", mem_y[0]);
    end

    $display("N = %0d: erro maximo contra a conta exata: arredondado %.3f LSB, truncado (antigo) %.3f LSB",
             N, max_arred, max_trunc);
    if (erros == 0 && max_arred <= 0.5)
        $display("TUDO OK: %0d amostras de y, arredondamento na saida", NY);
    else
        $display("FALHOU: %0d erro(s)", erros);
    $finish;
end

initial begin
    #(64'd40 * N * N * 20 + 1000000);
    $display("FALHOU: tempo esgotado, o conv1d nao terminou");
    $finish;
end

endmodule
