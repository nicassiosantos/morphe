// =============================================================================
// tb_iir_sos.v -- testbench do biquad, comparado BIT A BIT contra o modelo
// em Python (Python/iir_design.py, filtra_sos_fixo).
//
// Nao compara "parecido": compara inteiro por inteiro. Um filtro IIR em
// ponto fixo depende do arredondamento exato -- o erro volta pela
// realimentacao -- entao "quase igual" nao prova nada. Se o RTL e o modelo
// divergirem em um LSB numa amostra, divergem para sempre a partir dali.
//
// Os arquivos vem do gera_vetores_iir.py:
//   vetores_x.hex     amostras de entrada, Q15.16 em hexadecimal
//   vetores_y.hex     saida esperada, do modelo em Python
//   vetores_coef.hex  b0 b1 b2 a1 a2, uma por linha
//
// Rodar:
//   iverilog -g2012 -o tb.vvp tb_iir_sos.v iir_sos.v \
//            memory_read_controller.v memory_write_controller.v
//   vvp tb.vvp
// =============================================================================

`timescale 1 ns / 1 ps

module tb_iir_sos;

    localparam DATA_WIDTH  = 32;
    localparam ADDR_N_BITS = 10;
    localparam N_SAMPLES   = 256;

    reg clk = 1'b0;
    reg reset_n = 1'b0;
    reg start = 1'b0;
    wire done, error_sat;
    wire [2:0] estado;

    always #10 clk = ~clk;      // 50 MHz

    // --- Coeficientes ---
    reg signed [DATA_WIDTH-1:0] coef [0:4];
    wire signed [DATA_WIDTH-1:0] b0 = coef[0];
    wire signed [DATA_WIDTH-1:0] b1 = coef[1];
    wire signed [DATA_WIDTH-1:0] b2 = coef[2];
    wire signed [DATA_WIDTH-1:0] a1 = coef[3];
    wire signed [DATA_WIDTH-1:0] a2 = coef[4];

    // --- Memorias simuladas, com a latencia de 1 ciclo da SRAM real ---
    reg [DATA_WIDTH-1:0] mem_x [0:(1<<ADDR_N_BITS)-1];
    reg [DATA_WIDTH-1:0] mem_y [0:(1<<ADDR_N_BITS)-1];
    reg [DATA_WIDTH-1:0] esperado [0:(1<<ADDR_N_BITS)-1];

    wire [ADDR_N_BITS-1:0] x_addr, y_addr;
    wire x_cs, x_clken, x_we;
    wire y_cs, y_clken, y_we;
    wire [DATA_WIDTH-1:0] y_wdata;
    reg  [DATA_WIDTH-1:0] x_rdata;

    always @(posedge clk) begin
        if (x_cs && x_clken && !x_we)
            x_rdata <= mem_x[x_addr];
        if (y_cs && y_clken && y_we)
            mem_y[y_addr] <= y_wdata;
    end

    iir_sos #(
        .DATA_WIDTH  (DATA_WIDTH),
        .FRAC_BITS   (16),
        .ACC_WIDTH   (72),
        .N_SAMPLES   (N_SAMPLES),
        .ADDR_N_BITS (ADDR_N_BITS)
    ) dut (
        .clk (clk), .reset_n (reset_n), .start (start),
        .done (done), .error_sat (error_sat),
        .b0 (b0), .b1 (b1), .b2 (b2), .a1 (a1), .a2 (a2),
        .xn_sram_readdata   (x_rdata),
        .xn_sram_address    (x_addr),
        .xn_sram_chipselect (x_cs),
        .xn_sram_clken      (x_clken),
        .xn_sram_write      (x_we),
        .yn_sram_address    (y_addr),
        .yn_sram_wdata      (y_wdata),
        .yn_sram_chipselect (y_cs),
        .yn_sram_clken      (y_clken),
        .yn_sram_write      (y_we),
        .debug_state        (estado)
    );

    integer i;
    integer erros;
    integer primeiro_erro;
    integer ciclos;

    initial begin
        $readmemh("vetores_coef.hex", coef, 0, 4);
        $readmemh("vetores_x.hex",    mem_x,    0, N_SAMPLES - 1);
        $readmemh("vetores_y.hex",    esperado, 0, N_SAMPLES - 1);

        $display("=========================================================");
        $display("tb_iir_sos -- %0d amostras, Q15.16", N_SAMPLES);
        $display("coeficientes (Q15.16 como inteiro):");
        $display("  b0=%0d  b1=%0d  b2=%0d", coef[0], coef[1], coef[2]);
        $display("  a1=%0d  a2=%0d", coef[3], coef[4]);
        $display("=========================================================");

        repeat (4) @(negedge clk);
        reset_n = 1'b1;
        repeat (4) @(negedge clk);

        start = 1'b1;
        @(negedge clk);
        @(negedge clk);
        start = 1'b0;

        ciclos = 0;
        while (!done && ciclos < 2000000) begin
            @(posedge clk);
            ciclos = ciclos + 1;
        end

        if (!done) begin
            $display("FALHOU: done nunca subiu (%0d ciclos, estado=%0d)",
                     ciclos, estado);
            $finish;
        end

        erros = 0;
        primeiro_erro = -1;
        for (i = 0; i < N_SAMPLES; i = i + 1) begin
            if (mem_y[i] !== esperado[i]) begin
                erros = erros + 1;
                if (primeiro_erro < 0) begin
                    primeiro_erro = i;
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
