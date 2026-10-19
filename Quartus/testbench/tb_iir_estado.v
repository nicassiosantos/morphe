// =============================================================================
// tb_iir_estado.v -- o estado do iir_cascade passando de um bloco ao outro.
//
// O testbench faz o papel do HPS (do servidor): roda o bloco 0 com o estado
// zero, le o estado final que o bloco gravou na SRAM dos coeficientes,
// copia para a regiao do estado inicial, liga o modo e roda o bloco 1, e
// assim por diante. A saida concatenada tem de ser BIT A BIT a do modelo em
// Python filtrando o sinal inteiro de uma vez (gera_vetores_iir.py estado).
//
// Confere tambem:
//   - o estado gravado ao fim do bloco 0 contra o do modelo;
//   - a marca (EST_MARCA = "EST1"), que diz ao servidor que o bitstream
//     devolve o estado;
//   - o modo 0 depois de tudo: o bloco 0 de novo tem de dar o mesmo de
//     antes, apesar do estado que sobrou nos registradores.
//
// Arquivos (gera_vetores_iir.py, caso "estado"):
//   vetores_coef.hex, vetores_nsec.hex, vetores_x.hex, vetores_y.hex
//   vetores_est.hex   estado ao fim do bloco 0: x1 x2 y1 y2 por secao
// =============================================================================

`timescale 1 ns / 1 ps

module tb_iir_estado;

    localparam DATA_WIDTH  = 32;
    localparam ADDR_N_BITS = 10;
    localparam COEF_BITS   = 8;
    localparam N_SAMPLES   = 256;
    localparam MAX_SECOES  = 16;
    localparam N_BLOCOS    = 3;

    localparam EST_MODO  = 120;
    localparam EST_MARCA = 121;
    localparam EST_IN    = 128;
    localparam EST_OUT   = 192;

    reg clk = 1'b0;
    reg reset_n = 1'b0;
    reg start = 1'b0;
    wire done, error_sat;
    wire [3:0] estado;

    always #10 clk = ~clk;

    reg [DATA_WIDTH-1:0] mem_coef [0:(1<<COEF_BITS)-1];
    reg [DATA_WIDTH-1:0] mem_x    [0:(1<<ADDR_N_BITS)-1];
    reg [DATA_WIDTH-1:0] mem_y    [0:(1<<ADDR_N_BITS)-1];
    reg [DATA_WIDTH-1:0] sinal    [0:N_BLOCOS*N_SAMPLES-1];
    reg [DATA_WIDTH-1:0] esperado [0:N_BLOCOS*N_SAMPLES-1];
    reg [DATA_WIDTH-1:0] est_esp  [0:4*MAX_SECOES-1];
    reg [DATA_WIDTH-1:0] nsec_arq [0:0];

    wire [COEF_BITS-1:0]   c_addr;
    wire [ADDR_N_BITS-1:0] x_addr, y_addr;
    wire c_cs, c_clken, c_we;
    wire x_cs, x_clken, x_we;
    wire y_cs, y_clken, y_we;
    wire [DATA_WIDTH-1:0] y_wdata, c_wdata;
    reg  [DATA_WIDTH-1:0] c_rdata, x_rdata;

    // SRAM com a latencia de 1 ciclo da memoria real; a dos coeficientes
    // agora tambem e escrita pelo bloco (estado final e marca)
    always @(posedge clk) begin
        if (c_cs && c_clken && !c_we) c_rdata <= mem_coef[c_addr];
        if (c_cs && c_clken &&  c_we) mem_coef[c_addr] <= c_wdata;
        if (x_cs && x_clken && !x_we) x_rdata <= mem_x[x_addr];
        if (y_cs && y_clken &&  y_we) mem_y[y_addr] <= y_wdata;
    end

    reg [4:0] n_secoes;

    iir_cascade #(
        .DATA_WIDTH       (DATA_WIDTH),
        .FRAC_BITS        (16),
        .ACC_WIDTH        (72),
        .N_SAMPLES        (N_SAMPLES),
        .ADDR_N_BITS      (ADDR_N_BITS),
        .MAX_SECOES       (MAX_SECOES),
        .COEF_ADDR_N_BITS (COEF_BITS)
    ) dut (
        .clk (clk), .reset_n (reset_n), .start (start),
        .done (done), .error_sat (error_sat),
        .n_secoes (n_secoes),
        .coef_sram_readdata   (c_rdata),
        .coef_sram_address    (c_addr),
        .coef_sram_chipselect (c_cs),
        .coef_sram_clken      (c_clken),
        .coef_sram_write      (c_we),
        .coef_sram_wdata      (c_wdata),
        .xn_sram_readdata     (x_rdata),
        .xn_sram_address      (x_addr),
        .xn_sram_chipselect   (x_cs),
        .xn_sram_clken        (x_clken),
        .xn_sram_write        (x_we),
        .yn_sram_address      (y_addr),
        .yn_sram_wdata        (y_wdata),
        .yn_sram_chipselect   (y_cs),
        .yn_sram_clken        (y_clken),
        .yn_sram_write        (y_we),
        .debug_state          (estado)
    );

    integer i, b, erros, erros_est, falhas, ciclos;

    // Uma execucao do bloco: o que o servidor faz entre o start e o done.
    task roda_bloco(input integer bloco, input integer modo);
        begin
            for (i = 0; i < N_SAMPLES; i = i + 1)
                mem_x[i] = sinal[bloco * N_SAMPLES + i];
            mem_coef[EST_MODO]  = modo;
            mem_coef[EST_MARCA] = 0;
            @(negedge clk);
            start = 1'b1;
            ciclos = 0;
            while (!done && ciclos < 5000000) begin
                @(posedge clk);
                ciclos = ciclos + 1;
            end
            @(negedge clk);
            start = 1'b0;
            @(negedge clk);
            if (!done && ciclos >= 5000000) begin
                $display("FALHOU: done nunca subiu (estado=%0d)", estado);
                $finish;
            end
        end
    endtask

    task confere_bloco(input integer bloco);
        begin
            erros = 0;
            for (i = 0; i < N_SAMPLES; i = i + 1)
                if (mem_y[i] !== esperado[bloco * N_SAMPLES + i]) begin
                    if (erros == 0)
                        $display("   primeira divergencia em n=%0d: RTL %0d, Python %0d",
                                 bloco * N_SAMPLES + i, $signed(mem_y[i]),
                                 $signed(esperado[bloco * N_SAMPLES + i]));
                    erros = erros + 1;
                end
            $display("bloco %0d: %0d ciclos, %0d amostras erradas de %0d, marca %s",
                     bloco, ciclos, erros, N_SAMPLES,
                     mem_coef[EST_MARCA] == 32'h45535431 ? "ok" : "AUSENTE");
            if (erros != 0 || mem_coef[EST_MARCA] != 32'h45535431)
                falhas = falhas + 1;
        end
    endtask

    initial begin
        $readmemh("vetores_nsec.hex", nsec_arq, 0, 0);
        n_secoes = nsec_arq[0][4:0];
        $readmemh("vetores_coef.hex", mem_coef, 0, n_secoes * 5 - 1);
        $readmemh("vetores_x.hex",    sinal,    0, N_BLOCOS * N_SAMPLES - 1);
        $readmemh("vetores_y.hex",    esperado, 0, N_BLOCOS * N_SAMPLES - 1);
        $readmemh("vetores_est.hex",  est_esp,  0, n_secoes * 4 - 1);
        falhas = 0;

        $display("=========================================================");
        $display("tb_iir_estado -- %0d blocos de %0d, %0d secoes, Q15.16",
                 N_BLOCOS, N_SAMPLES, n_secoes);
        $display("=========================================================");

        repeat (4) @(negedge clk);
        reset_n = 1'b1;
        repeat (4) @(negedge clk);

        // bloco 0: estado zero (modo 0), como sempre foi
        roda_bloco(0, 0);
        confere_bloco(0);

        // o estado que o bloco gravou, contra o do modelo
        erros_est = 0;
        for (i = 0; i < n_secoes * 4; i = i + 1)
            if (mem_coef[EST_OUT + i] !== est_esp[i]) erros_est = erros_est + 1;
        $display("estado ao fim do bloco 0: %0d de %0d palavras erradas",
                 erros_est, n_secoes * 4);
        if (erros_est != 0) falhas = falhas + 1;

        // blocos seguintes: o estado final vira o inicial (modo 1)
        for (b = 1; b < N_BLOCOS; b = b + 1) begin
            for (i = 0; i < n_secoes * 4; i = i + 1)
                mem_coef[EST_IN + i] = mem_coef[EST_OUT + i];
            roda_bloco(b, 1);
            confere_bloco(b);
        end

        // modo 0 de novo: os registradores ainda guardam o estado do
        // ultimo bloco, e o resultado tem de ser o do bloco 0
        $display("modo 0 depois do encadeamento (tem de zerar o estado):");
        roda_bloco(0, 0);
        confere_bloco(0);

        $display("---------------------------------------------------------");
        if (falhas == 0)
            $display("RESULTADO: BIT A BIT IGUAL ao sinal inteiro de uma vez");
        else
            $display("RESULTADO: FALHOU (%0d conferencias)", falhas);
        $display("=========================================================");
        $finish;
    end

endmodule
