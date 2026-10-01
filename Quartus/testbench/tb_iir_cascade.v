// =============================================================================
// tb_iir_cascade.v -- testbench da cascata, comparada BIT A BIT contra o
// modelo em Python (Python/iir_design.py, filtra_sos_fixo).
//
// A comparacao aqui prova mais do que a da secao unica. O modelo em Python
// varre secao por fora e amostra por dentro; o RTL varre amostra por fora e
// secao por dentro. Se as duas ordens de varredura produzem o mesmo bit em
// todas as amostras, a equivalencia entre os dois esquemas -- que o
// cabecalho do iir_cascade.v afirma -- deixa de ser argumento e vira
// medida.
//
// Arquivos gerados pelo gera_vetores_iir.py (caso "cascata"):
//   vetores_coef.hex  5 palavras por secao: b0 b1 b2 a1 a2
//   vetores_nsec.hex  numero de secoes
//   vetores_x.hex     entrada
//   vetores_y.hex     saida esperada
// =============================================================================

`timescale 1 ns / 1 ps

module tb_iir_cascade;

    localparam DATA_WIDTH   = 32;
    localparam ADDR_N_BITS  = 10;
    localparam COEF_BITS    = 8;
    localparam N_SAMPLES    = 256;
    localparam MAX_SECOES   = 16;

    reg clk = 1'b0;
    reg reset_n = 1'b0;
    reg start = 1'b0;
    wire done, error_sat;
    wire [3:0] estado;

    always #10 clk = ~clk;

    reg [DATA_WIDTH-1:0] mem_coef [0:(1<<COEF_BITS)-1];
    reg [DATA_WIDTH-1:0] mem_x    [0:(1<<ADDR_N_BITS)-1];
    reg [DATA_WIDTH-1:0] mem_y    [0:(1<<ADDR_N_BITS)-1];
    reg [DATA_WIDTH-1:0] esperado [0:(1<<ADDR_N_BITS)-1];
    reg [DATA_WIDTH-1:0] nsec_arq [0:0];

    wire [COEF_BITS-1:0]   c_addr;
    wire [ADDR_N_BITS-1:0] x_addr, y_addr;
    wire c_cs, c_clken, c_we;
    wire x_cs, x_clken, x_we;
    wire y_cs, y_clken, y_we;
    wire [DATA_WIDTH-1:0] y_wdata;
    reg  [DATA_WIDTH-1:0] c_rdata, x_rdata;

    // SRAM com a latencia de 1 ciclo da memoria real
    always @(posedge clk) begin
        if (c_cs && c_clken && !c_we) c_rdata <= mem_coef[c_addr];
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

    integer i, erros, primeiro, ciclos;

    initial begin
        $readmemh("vetores_nsec.hex", nsec_arq, 0, 0);
        n_secoes = nsec_arq[0][4:0];
        $readmemh("vetores_coef.hex", mem_coef, 0, n_secoes * 5 - 1);
        $readmemh("vetores_x.hex",    mem_x,    0, N_SAMPLES - 1);
        $readmemh("vetores_y.hex",    esperado, 0, N_SAMPLES - 1);

        $display("=========================================================");
        $display("tb_iir_cascade -- %0d amostras, %0d secoes, Q15.16",
                 N_SAMPLES, n_secoes);
        for (i = 0; i < n_secoes; i = i + 1)
            $display("  secao %0d: b0=%0d b1=%0d b2=%0d a1=%0d a2=%0d",
                     i, $signed(mem_coef[i*5+0]), $signed(mem_coef[i*5+1]),
                     $signed(mem_coef[i*5+2]), $signed(mem_coef[i*5+3]),
                     $signed(mem_coef[i*5+4]));
        $display("=========================================================");

        repeat (4) @(negedge clk);
        reset_n = 1'b1;
        repeat (4) @(negedge clk);
        start = 1'b1;
        @(negedge clk);
        @(negedge clk);
        start = 1'b0;

        ciclos = 0;
        while (!done && ciclos < 5000000) begin
            @(posedge clk);
            ciclos = ciclos + 1;
        end

        if (!done) begin
            $display("FALHOU: done nunca subiu (%0d ciclos, estado=%0d)",
                     ciclos, estado);
            $finish;
        end

        erros = 0;
        primeiro = -1;
        for (i = 0; i < N_SAMPLES; i = i + 1) begin
            if (mem_y[i] !== esperado[i]) begin
                erros = erros + 1;
                if (primeiro < 0) begin
                    primeiro = i;
                    $display("primeira divergencia em n=%0d:", i);
                    $display("   RTL    = %0d (0x%08h)",
                             $signed(mem_y[i]), mem_y[i]);
                    $display("   Python = %0d (0x%08h)",
                             $signed(esperado[i]), esperado[i]);
                    $display("   diff   = %0d LSB",
                             $signed(mem_y[i]) - $signed(esperado[i]));
                end
            end
        end

        $display("---------------------------------------------------------");
        $display("ciclos ate done : %0d  (%0d por amostra)",
                 ciclos, ciclos / N_SAMPLES);
        $display("error_sat       : %0d", error_sat);
        $display("amostras erradas: %0d de %0d", erros, N_SAMPLES);
        if (erros == 0)
            $display("RESULTADO: BIT A BIT IGUAL ao modelo em Python");
        else
            $display("RESULTADO: FALHOU");
        $display("=========================================================");
        $finish;
    end

endmodule
