// =============================================================================
// tb_adc_captura.v -- testbench do adc_captura contra um modelo do LTC2308.
//
// O modelo segue a folha de dados no que o controlador depende:
//   - a conversao comeca na subida do CONVST e leva T_CONV_NS;
//   - com CONVST baixo e a conversao pronta, o SDO mostra B11; cada descida
//     do SCLK passa ao bit seguinte, com atraso de saida de TDSDO_NS;
//   - o SDI e lido nas SEIS primeiras subidas do SCLK, e a palavra vale para
//     a PROXIMA conversao.
// E confere as restricoes que o controlador precisa respeitar: nada de SCLK
// antes do fim da conversao, SCLK dentro do limite de 40 MHz, tempo de
// aquisicao minimo antes de cada CONVST.
//
// O "sinal analogico" do modelo e um codigo que depende do instante exato
// da subida do CONVST e do canal selecionado. Assim a mesma comparacao
// prova tres coisas: o instante de cada amostra, o canal usado em cada
// conversao e a ordem dos bits na leitura.
// =============================================================================

`timescale 1 ns / 1 ps

module tb_adc_captura;

    localparam ADDR_BITS = 15;
    localparam DIV_MIN   = 250;
    localparam PROF      = 1 << ADDR_BITS;

    // tempos do LTC2308 (folha de dados)
    localparam real T_CONV_NS  = 1600.0;  // tCONV maximo
    localparam real TDSDO_NS   = 15.0;    // atraso do SDO apos a descida do SCLK
    localparam real T_ACQ_NS   = 240.0;   // aquisicao minima
    localparam real SCLK_MIN_NS = 25.0;   // periodo minimo (40 MHz)

    reg clk = 1'b0;
    reg reset_n = 1'b0;
    always #10 clk = ~clk;              // 50 MHz

    reg         start = 1'b0;
    wire        done;
    reg  [31:0] divisor;
    reg  [15:0] n_amostras;
    reg  [5:0]  config_adc;
    reg         continuo = 1'b0;
    wire [31:0] contador;

    wire convst, sclk, din;
    reg  dout = 1'b0;

    wire [ADDR_BITS-1:0] ram_address;
    wire [31:0]          ram_wdata;
    wire                 ram_write, ram_cs, ram_clken;

    reg [31:0] mem [0:PROF-1];
    always @(posedge clk)
        if (ram_cs && ram_clken && ram_write) mem[ram_address] <= ram_wdata;

    adc_captura #(.ADDR_BITS(ADDR_BITS), .DIV_MIN(DIV_MIN)) dut (
        .clk(clk), .reset_n(reset_n),
        .start(start), .done(done),
        .divisor(divisor), .n_amostras(n_amostras), .config_adc(config_adc),
        .continuo(continuo), .contador(contador),
        .adc_convst(convst), .adc_sclk(sclk), .adc_din(din), .adc_dout(dout),
        .ram_address(ram_address), .ram_wdata(ram_wdata), .ram_write(ram_write),
        .ram_chipselect(ram_cs), .ram_clken(ram_clken)
    );

    // =========================================================================
    // Modelo do LTC2308
    // =========================================================================
    integer erros = 0;

    reg  [5:0]  cfg_atual   = 6'b110110;  // de "antes": canal 3, para o quadro 0 destoar
    reg  [5:0]  cfg_proxima;
    reg  [5:0]  sdi_shift;
    integer     n_sdi;
    reg  [11:0] resultado;
    integer     n_sdo;
    real        t_convst, t_fim_leitura;
    reg         convertendo = 1'b0;

    // registro de cada conversao, para o testbench comparar depois
    integer     n_conv = 0;
    real        t_conv_log [0:4*PROF];
    reg [11:0]  val_log    [0:4*PROF];
    reg [2:0]   canal_log  [0:4*PROF];

    // Canal pela palavra: S/D=1 (entrada simples), canal = {S1, S0, O/S}.
    function [2:0] canal_de(input [5:0] c);
        canal_de = {c[3], c[2], c[4]};
    endfunction

    // O "sinal": depende do instante (em ciclos de 20 ns) e do canal.
    function [11:0] sinal(input real t_ns, input [2:0] ch);
        integer ciclos;
        begin
            ciclos = $rtoi(t_ns / 20.0 + 0.5);
            sinal = (ciclos * 37 + ch * 512) & 12'hFFF;
        end
    endfunction

    always @(posedge convst) begin
        if (convertendo)
            begin $display("ERRO: CONVST durante conversao em %0t", $time); erros = erros + 1; end
        if (n_conv > 0 && ($realtime - t_fim_leitura) < T_ACQ_NS)
            begin $display("ERRO: aquisicao curta (%0.1f ns) em %0t",
                           $realtime - t_fim_leitura, $time); erros = erros + 1; end
        t_convst    = $realtime;
        convertendo = 1'b1;
        resultado   = sinal($realtime, canal_de(cfg_atual));
        t_conv_log[n_conv] = $realtime;
        val_log[n_conv]    = resultado;
        canal_log[n_conv]  = canal_de(cfg_atual);
        n_conv = n_conv + 1;
        n_sdi  = 0;
        n_sdo  = 0;
        #(T_CONV_NS) convertendo = 1'b0;
    end

    // B11 aparece quando CONVST esta baixo e a conversao acabou
    always @(negedge convst) begin
        if (convertendo)
            begin $display("ERRO: CONVST baixou antes do fim da conversao em %0t", $time);
                  erros = erros + 1; end
        dout <= resultado[11];
    end

    real t_subida_ant = -1.0e9;
    always @(posedge sclk) begin
        if (convst || convertendo)
            begin $display("ERRO: SCLK com conversao em curso em %0t", $time); erros = erros + 1; end
        if ($realtime - t_subida_ant < SCLK_MIN_NS)
            begin $display("ERRO: SCLK acima de 40 MHz em %0t", $time); erros = erros + 1; end
        t_subida_ant = $realtime;
        if (n_sdi < 6) begin
            sdi_shift = {sdi_shift[4:0], din};
            n_sdi = n_sdi + 1;
            if (n_sdi == 6) cfg_proxima = sdi_shift;
        end
    end

    always @(negedge sclk) begin
        n_sdo = n_sdo + 1;
        if (n_sdo < 12) dout <= #(TDSDO_NS) resultado[11 - n_sdo];
        else            dout <= #(TDSDO_NS) 1'b0;
        if (n_sdo == 12) begin
            t_fim_leitura = $realtime;
            if (n_sdi == 6) cfg_atual = cfg_proxima;   // vale para a proxima conversao
        end
    end

    // =========================================================================
    // Casos
    // =========================================================================
    task captura(input [31:0] div, input [15:0] n, input [5:0] cfg,
                 input [8*24-1:0] nome);
        integer i, conv0, n_esperado, periodo, falhas;
        real dt;
        begin
            divisor = div; n_amostras = n; config_adc = cfg;
            n_esperado = (n == 0) ? 1 : ((n > PROF) ? PROF : n);
            periodo    = (div < DIV_MIN) ? DIV_MIN : div;
            conv0      = n_conv;
            for (i = 0; i < n_esperado; i = i + 1) mem[i] = 32'hDEADBEEF;

            // estimulos na descida do clock: mudar na subida disputa a mesma
            // borda com o registrador do DUT (no hardware o PIO e registrado)
            @(negedge clk); start = 1'b1;
            wait (done === 1'b1);
            @(negedge clk); start = 1'b0;
            wait (done === 1'b0);
            repeat (5) @(posedge clk);

            falhas = 0;
            if (n_conv - conv0 != n_esperado + 1) begin
                $display("  ERRO: %0d conversoes, esperado %0d",
                         n_conv - conv0, n_esperado + 1);
                falhas = falhas + 1;
            end
            for (i = 0; i < n_esperado; i = i + 1) begin
                // periodo exato entre conversoes consecutivas
                dt = t_conv_log[conv0 + i + 1] - t_conv_log[conv0 + i];
                if (dt != periodo * 20.0) begin
                    if (falhas < 5) $display("  ERRO: periodo %0.1f ns na amostra %0d", dt, i);
                    falhas = falhas + 1;
                end
                // a conversao do quadro i+1 usa o canal pedido
                if (canal_log[conv0 + i + 1] != canal_de(cfg)) begin
                    if (falhas < 5) $display("  ERRO: canal %0d na amostra %0d",
                                             canal_log[conv0 + i + 1], i);
                    falhas = falhas + 1;
                end
                // e o valor guardado e o daquela conversao, com os bits em ordem
                if (mem[i] !== {20'd0, val_log[conv0 + i + 1]}) begin
                    if (falhas < 5) $display("  ERRO: amostra %0d = %h, esperado %h",
                                             i, mem[i], val_log[conv0 + i + 1]);
                    falhas = falhas + 1;
                end
            end
            if (falhas == 0)
                $display("  OK  %0s: %0d amostras a %0d ciclos (fs = %0.1f Hz), canal %0d",
                         nome, n_esperado, periodo, 50.0e6 / periodo, canal_de(cfg));
            erros = erros + falhas;
        end
    endtask


    // Modo continuo: a RAM e um buffer circular. Enquanto roda, a cada amostra
    // nova confere a promessa do contador (contador = c -> amostra c-1 ja esta
    // no endereco (c-1) mod PROF). Depois baixa o start no meio de um quadro e
    // confere: o quadro em curso termina, nenhuma conversao nova comeca, os
    // periodos sao todos exatos e as ultimas PROF amostras na RAM sao as certas.
    integer vigia_conv0 = 0;
    reg     vigiando = 1'b0;
    integer falhas_vigia = 0;
    reg [31:0] cont_ant = 0;
    always @(negedge clk) begin
        if (vigiando && contador != cont_ant) begin
            if (contador != cont_ant + 1) begin
                if (falhas_vigia < 5) $display("  ERRO: contador pulou de %0d para %0d", cont_ant, contador);
                falhas_vigia = falhas_vigia + 1;
            end
            if (mem[(contador - 1) % PROF] !== {20'd0, val_log[vigia_conv0 + contador]}) begin
                if (falhas_vigia < 5) $display("  ERRO: contador = %0d mas a amostra %0d nao esta na RAM",
                                               contador, contador - 1);
                falhas_vigia = falhas_vigia + 1;
            end
            cont_ant = contador;
        end
    end

    task continua(input [31:0] div, input integer n_ate, input [5:0] cfg,
                  input [8*48-1:0] nome);
        integer i, conv0, total, falhas;
        real dt, t_baixou;
        begin
            divisor = div; n_amostras = 0; config_adc = cfg;
            conv0 = n_conv;
            vigia_conv0 = conv0;
            cont_ant = 0; falhas_vigia = 0;
            @(negedge clk); continuo = 1'b1; start = 1'b1;
            @(negedge clk);                 // o start zera o contador na borda seguinte
            if (contador !== 0) begin
                $display("  ERRO: contador nao zerou no start (%0d)", contador);
                falhas_vigia = falhas_vigia + 1;
            end
            cont_ant = 0;
            vigiando = 1'b1;
            wait (contador >= n_ate);
            // baixa o start no meio de um quadro qualquer
            repeat (div / 3) @(negedge clk);
            vigiando = 1'b0;          // o contador vai a zero no fim: nao e salto
            t_baixou = $realtime;
            start = 1'b0;
            wait (done === 1'b1);
            if ($realtime - t_baixou > div * 20.0 + 1000.0)
                begin $display("  ERRO: parou %0.1f ns depois do start baixar", $realtime - t_baixou);
                      falhas_vigia = falhas_vigia + 1; end
            repeat (3) @(negedge clk);
            continuo = 1'b0;
            wait (done === 1'b0);
            repeat (5) @(posedge clk);

            falhas = falhas_vigia;
            // todas as conversoes menos a descartada viraram amostra na RAM
            total = n_conv - conv0 - 1;
            if (cont_ant < total - 1) begin
                $display("  ERRO: o contador parou em %0d com %0d amostras", cont_ant, total);
                falhas = falhas + 1;
            end
            if (contador !== 0) begin
                $display("  ERRO: contador = %0d em repouso (devia ser 0)", contador);
                falhas = falhas + 1;
            end
            for (i = 0; i < total; i = i + 1) begin
                dt = t_conv_log[conv0 + i + 1] - t_conv_log[conv0 + i];
                if (dt != div * 20.0) begin
                    if (falhas < 5) $display("  ERRO: periodo %0.1f ns na amostra %0d", dt, i);
                    falhas = falhas + 1;
                end
                if (canal_log[conv0 + i + 1] != canal_de(cfg)) begin
                    if (falhas < 5) $display("  ERRO: canal errado na amostra %0d", i);
                    falhas = falhas + 1;
                end
            end
            for (i = total - PROF; i < total; i = i + 1) begin
                if (i >= 0 && mem[i % PROF] !== {20'd0, val_log[conv0 + i + 1]}) begin
                    if (falhas < 5) $display("  ERRO: RAM[%0d] = %h, esperado %h (amostra %0d)",
                                             i % PROF, mem[i % PROF], val_log[conv0 + i + 1], i);
                    falhas = falhas + 1;
                end
            end
            if (falhas == 0)
                $display("  OK  %0s: %0d amostras, RAM deu %0d voltas; contador coerente a cada amostra",
                         nome, total, total / PROF);
            erros = erros + falhas;
        end
    endtask

    initial begin
        divisor = 0; n_amostras = 0; config_adc = 0;
        repeat (5) @(posedge clk);
        reset_n = 1'b1;
        repeat (5) @(posedge clk);

        //                 divisor  n       S/D O/S S1 S0 UNI SLP
        captura(250,     20,    6'b100010, "fs maxima, CH0");
        captura(1000,    10,    6'b111010, "50 kHz, CH5");        // O/S=1 S1=1 S0=0 -> canal 5
        captura(10,      5,     6'b100110, "divisor abaixo do min");  // CH2, satura em 250
        captura(5000,    0,     6'b101010, "n = 0 vira 1");       // CH4
        captura(50000,   3,     6'b110010, "1 kHz, CH1");
        captura(250,     PROF,  6'b100010, "RAM cheia, CH0");
        continua(250,   40000, 6'b100110, "continua a 200 kHz, CH2, 40000 amostras");
        continua(1000,  33000, 6'b111010, "continua a 50 kHz, CH5, 33000 amostras");
        captura(1000,    10,    6'b100010, "captura unica depois da continua");

        if (erros == 0) $display("TUDO OK: adc_captura confere com o modelo do LTC2308.");
        else            $display("FALHOU: %0d erros.", erros);
        $finish;
    end

    // trava de seguranca
    initial begin
        #5_000_000_000;
        $display("FALHOU: tempo esgotado");
        $finish;
    end

endmodule
