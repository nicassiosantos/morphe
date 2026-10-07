// Testbench do conv_aluno (roteiro da convolucao, docs/roteiro-conv, A4).
//
// As tres memorias aqui imitam as do Platform Designer: leitura com UM ciclo
// de latencia (o dado sai um ciclo depois de o endereco estar no fio) e
// escrita na borda do relogio quando y_we = 1. Cada caso escreve x e h,
// pulsa o start como o servidor faz, espera o done e compara y com a conta
// feita aqui mesmo, do jeito do conv1d (produto em 64 bits, bits [47:16],
// acumulador de 32 bits).
//
// Rodar, de dentro de Quartus/:
//   iverilog -g2005 -o /tmp/tb_conv.vvp testbench/tb_conv_aluno.v conv_aluno.v
//   vvp /tmp/tb_conv.vvp
// A ultima linha deve ser TUDO OK. Com -DGRANDE no iverilog, roda tambem o
// caso 1024 x 1024 (o maior que a placa aceita; leva alguns segundos).
`timescale 1 ns / 1 ps
module tb_conv_aluno;
    localparam NX_MAX = 1024, NH_MAX = 1024, NY_MAX = 2048;
    localparam [31:0] SENTINELA = 32'hDEADBEEF;   // y que ninguem escreveu

    reg clk = 0, reset_n = 0, start = 0;
    always #10 clk = ~clk;                        // 50 MHz

    reg  [10:0] nx, nh;
    wire        done;
    wire [9:0]  x_addr, h_addr;
    wire [10:0] y_addr;
    wire [31:0] y_data;
    wire        y_we;

    // --- as memorias, com a latencia das do Platform Designer ---
    reg [31:0] xm [0:NX_MAX-1];
    reg [31:0] hm [0:NH_MAX-1];
    reg [31:0] ym [0:NY_MAX-1];
    reg [31:0] x_q, h_q;
    always @(posedge clk) begin
        x_q <= xm[x_addr];
        h_q <= hm[h_addr];
        if (y_we) ym[y_addr] <= y_data;
    end

    conv_aluno dut (
        .clk (clk), .reset_n (reset_n),
        .start (start), .done (done), .nx (nx), .nh (nh),
        .x_addr (x_addr), .x_data (x_q),
        .h_addr (h_addr), .h_data (h_q),
        .y_addr (y_addr), .y_data (y_data), .y_we (y_we)
    );

    integer erros = 0;
    integer i, k, n;

    // a conta de referencia, igual a do conv1d
    function [31:0] y_ref(input integer nn);
        reg signed [63:0] p;
        reg signed [31:0] a;
        integer kk;
        begin
            a = 0;
            for (kk = 0; kk < nx; kk = kk + 1)
                if (nn - kk >= 0 && nn - kk < nh) begin
                    p = $signed(xm[kk]) * $signed(hm[nn - kk]);
                    a = a + p[47:16];
                end
            y_ref = a;
        end
    endfunction

    // dispara como o servidor: start 0 -> 1, espera done, start -> 0
    task rodar(input [8*40-1:0] nome);
        integer ciclos, errados, limite;
        begin
            // folga de 20 ciclos por produto: o gabarito usa 4
            limite = 20 * nx * nh + 20 * (nx + nh) + 1000;
            for (i = 0; i < NY_MAX; i = i + 1) ym[i] = SENTINELA;
            @(negedge clk) start = 1;
            ciclos = 0;
            while (done !== 1'b1 && ciclos < limite) begin
                @(posedge clk); ciclos = ciclos + 1;
            end
            if (done !== 1'b1) begin
                $display("ERRO  %0s: done nao subiu em %0d ciclos", nome, limite);
                erros = erros + 1;
            end else begin
                errados = 0;
                for (n = 0; n < nx + nh - 1; n = n + 1)
                    if (ym[n] !== y_ref(n)) begin
                        if (errados < 5)
                            $display("      y[%0d] = %h, esperado %h", n, ym[n], y_ref(n));
                        errados = errados + 1;
                    end
                for (n = nx + nh - 1; n < NY_MAX; n = n + 1)
                    if (ym[n] !== SENTINELA) begin
                        if (errados < 5)
                            $display("      y[%0d] escrito fora da saida (so ha %0d amostras)", n, nx + nh - 1);
                        errados = errados + 1;
                    end
                if (errados == 0)
                    $display("ok    %0s  (nx=%0d nh=%0d, %0d ciclos)", nome, nx, nh, ciclos);
                else begin
                    $display("ERRO  %0s  (%0d amostras erradas)", nome, errados);
                    erros = erros + 1;
                end
            end
            @(negedge clk) start = 0;
            ciclos = 0;
            while (done !== 1'b0 && ciclos < 100) begin
                @(posedge clk); ciclos = ciclos + 1;
            end
            if (done !== 1'b0) begin
                $display("ERRO  %0s: done nao voltou a 0 com start = 0", nome);
                erros = erros + 1;
            end
            repeat (3) @(posedge clk);
        end
    endtask

    // valor real -> Q15.16
    function [31:0] q(input real v);
        q = $rtoi(v * 65536.0);
    endfunction

    initial begin
        nx = 1; nh = 1;
        repeat (3) @(posedge clk);
        reset_n = 1;
        repeat (2) @(posedge clk);

        // 1. Exemplo 2 do artigo: y = {1, 4, 8, 8, 3, -2, -1}
        nx = 4; nh = 4;
        xm[0] = q(1); xm[1] = q(2); xm[2] = q(3); xm[3] = q(1);
        hm[0] = q(1); hm[1] = q(2); hm[2] = q(1); hm[3] = q(-1);
        rodar("Exemplo 2 do artigo");
        if (ym[0] !== q(1) || ym[1] !== q(4) || ym[2] !== q(8) || ym[3] !== q(8) ||
            ym[4] !== q(3) || ym[5] !== q(-2) || ym[6] !== q(-1)) begin
            $display("ERRO  Exemplo 2: y nao e {1,4,8,8,3,-2,-1}");
            erros = erros + 1;
        end

        // 2. uma amostra de cada: 2,5 * (-1,5) = -3,75
        nx = 1; nh = 1; xm[0] = q(2.5); hm[0] = q(-1.5);
        rodar("1 x 1, fracao e sinal");
        if (ym[0] !== q(-3.75)) begin
            $display("ERRO  1 x 1: y[0] = %h, esperado %h", ym[0], q(-3.75));
            erros = erros + 1;
        end

        // 3. h maior que x (kmin e kmax trocam de papel)
        nx = 3; nh = 6;
        for (i = 0; i < 3; i = i + 1) xm[i] = q(i + 1);
        for (i = 0; i < 6; i = i + 1) hm[i] = q(0.5 * i - 1);
        rodar("h maior que x");

        // 4. valores fracionarios quaisquer, de -8 a +8
        nx = 50; nh = 17;
        for (i = 0; i < 50; i = i + 1) xm[i] = $random % (8 * 65536);
        for (i = 0; i < 17; i = i + 1) hm[i] = $random % (8 * 65536);
        rodar("aleatorio 50 x 17");

        // 5. os extremos dos enderecos: x e h com 1024 amostras
        nx = 1024; nh = 3;
        for (i = 0; i < 1024; i = i + 1) xm[i] = $random % (4 * 65536);
        for (i = 0; i < 3; i = i + 1)    hm[i] = $random % (4 * 65536);
        rodar("x com 1024 amostras");
        nx = 3; nh = 1024;
        for (i = 0; i < 3; i = i + 1)    xm[i] = $random % (4 * 65536);
        for (i = 0; i < 1024; i = i + 1) hm[i] = $random % (4 * 65536);
        rodar("h com 1024 amostras");

        // 6. de novo o Exemplo 2: o modulo volta ao repouso e roda outra vez
        nx = 4; nh = 4;
        xm[0] = q(1); xm[1] = q(2); xm[2] = q(3); xm[3] = q(1);
        hm[0] = q(1); hm[1] = q(2); hm[2] = q(1); hm[3] = q(-1);
        rodar("segunda rodada seguida");

`ifdef GRANDE
        // 7. o maior caso: 1024 x 1024 -> 2047 amostras
        nx = 1024; nh = 1024;
        for (i = 0; i < 1024; i = i + 1) xm[i] = $random % (2 * 65536);
        for (i = 0; i < 1024; i = i + 1) hm[i] = $random % (2 * 65536);
        rodar("1024 x 1024");
`endif

        if (erros == 0) $display("TUDO OK");
        else            $display("%0d ERRO(S)", erros);
        $finish;
    end
endmodule
