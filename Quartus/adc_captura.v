// =============================================================================
// adc_captura.v -- captura do LTC2308 (ADC da DE1-SoC) a uma taxa fixa.
//
// Por que um controlador proprio: o IP do University Program
// (altera_up_avalon_adc_mega) converte sem parar, na velocidade dele, e
// entrega so o ULTIMO valor de cada canal. Pegar esse valor a cada 1/fs
// deixa o instante da amostra incerto em alguns microssegundos, e isso vira
// ruido que cresce com a frequencia do sinal (docs/ADC.md). Aqui cada
// conversao comeca exatamente no ciclo em que o contador de periodo zera:
// o instante de amostragem e a borda de subida do CONVST, com a incerteza de
// um ciclo de 50 MHz fixada pelo projeto, e nao pela varredura.
//
// Dois modos, escolhidos pelo `continuo` no start:
//
//   captura unica (continuo = 0; mesmo aperto de mao do iir_cascade)
//     1. o HPS escreve `divisor` (fs = 50 MHz / divisor), `n_amostras` e
//        `config_adc` (palavra de 6 bits do LTC2308) nos PIOs;
//     2. borda de subida em `start` dispara a captura;
//     3. `done` sobe quando as n amostras estao na RAM e fica em 1 ate o
//        HPS baixar `start`.
//
//   continuo (continuo = 1): a RAM vira um buffer circular. A amostra i vai
//     para o endereco i mod 2^ADDR_BITS, sem fim, ate o HPS baixar `start`;
//     o quadro em curso termina (no maximo um periodo) e o bloco volta ao
//     repouso -- `done` pisca um ciclo so, entao o HPS espera um periodo em
//     vez de esperar o `done`. `contador` diz quantas amostras
//     ja estao na RAM; o HPS copia as novas enquanto a captura segue. Se ele
//     atrasar mais que o tamanho da RAM, amostras sao sobrescritas antes de
//     lidas -- quem detecta e o HPS, relendo o contador depois de copiar
//     (morphe_server.c, handle_adc_continuo). Nao ha buraco no tempo entre
//     blocos: o hardware nao para entre uma leitura e outra.
//
// `contador` sobe no MESMO ciclo em que a RAM grava a amostra: quando o HPS
// le contador = c, as amostras 0..c-1 ja estao na memoria. Em repouso vale 0.
//
// Um quadro por amostra, a partir do zero do contador de periodo:
//
//   fase 0                  CONVST sobe: a conversao comeca (instante da amostra)
//   fase T_CONV             CONVST desce: o LTC2308 poe o bit 11 no SDO
//   fase T_CONV+2 ...       12 pulsos de SCLK: le B11..B0 do SDO e, nos seis
//                           primeiros, envia a palavra de configuracao pelo SDI
//   fim da leitura          a amostra vai para a RAM
//   fase divisor-1          o contador volta a zero e o proximo quadro comeca
//
// A palavra de configuracao enviada num quadro vale para a conversao do
// quadro SEGUINTE (e assim no LTC2308). Por isso o primeiro quadro de cada
// captura e descartado: a conversao dele usa a configuracao de antes. Sao
// n+1 conversoes para n amostras; a primeira amostra guardada e a do quadro 1.
//
// Convencoes do barramento serial, as mesmas do IP do University Program
// para o LTC2308 (altera_up_avalon_adv_adc.v): SCLK parado em 0; o SDI muda
// na descida do SCLK e o LTC2308 o le na subida; o SDO e lido na mesma borda
// de clock que sobe o SCLK, ou seja, antes da subida, quando esta estavel
// desde a descida anterior. CONVST fica alto durante toda a conversao.
//
// A amostra vai para a RAM crua, nos 12 bits baixos da palavra de 32. Em
// modo bipolar (bit UNI = 0) ela e complemento de dois de 12 bits; quem le
// estende o sinal (o servidor faz isso).
// =============================================================================

module adc_captura #(
    parameter ADDR_BITS = 15,     // 2^15 = 32768 amostras na RAM de captura
    parameter DIV_MIN   = 250,    // 50 MHz / 250 = 200 kHz, a fs maxima
    parameter T_CONV    = 96,     // ciclos com CONVST alto: 1,92 us > tCONV maximo
    parameter SCLK_MEIO = 2       // meio periodo do SCLK em ciclos: 12,5 MHz
) (
    input  wire                 clk,
    input  wire                 reset_n,

    // PIOs de controle
    input  wire                 start,        // HPS -> FPGA, borda de subida dispara
    output reg                  done,         // FPGA -> HPS
    input  wire [31:0]          divisor,      // periodo de amostragem em ciclos
    input  wire [15:0]          n_amostras,   // 1 .. 2^ADDR_BITS (so na captura unica)
    input  wire [5:0]           config_adc,   // S/D O/S S1 S0 UNI SLP
    input  wire                 continuo,     // 1 = buffer circular ate baixar start
    output reg  [31:0]          contador,     // amostras ja gravadas nesta captura

    // LTC2308
    output reg                  adc_convst,
    output reg                  adc_sclk,
    output reg                  adc_din,
    input  wire                 adc_dout,

    // RAM de captura, porta do FPGA (so escrita)
    output reg  [ADDR_BITS-1:0] ram_address,
    output reg  [31:0]          ram_wdata,
    output reg                  ram_write,
    output wire                 ram_chipselect,
    output wire                 ram_clken
);

    localparam INICIO_LEITURA = T_CONV + 2;
    localparam CICLOS_LEITURA = 12 * 2 * SCLK_MEIO;
    localparam PROFUNDIDADE   = 1 << ADDR_BITS;

    // O quadro inteiro tem que caber no periodo minimo, deixando ao menos
    // 240 ns (12 ciclos) de aquisicao antes do proximo CONVST.
    initial begin
        if (INICIO_LEITURA + CICLOS_LEITURA + 2 + 12 > DIV_MIN) begin
            $display("adc_captura: DIV_MIN=%0d curto demais para o quadro", DIV_MIN);
            $finish;
        end
    end

    assign ram_chipselect = 1'b1;
    assign ram_clken      = 1'b1;

    // ---- borda de subida do start -------------------------------------------
    reg start_d;
    always @(posedge clk or negedge reset_n)
        if (!reset_n) start_d <= 1'b0;
        else          start_d <= start;
    wire start_pulse = start & ~start_d;

    // ---- estado ----------------------------------------------------------------
    localparam S_IDLE = 2'd0, S_PREP = 2'd1, S_CAPT = 2'd2, S_DONE = 2'd3;
    reg [1:0]  estado;

    // Espera entre o start e o primeiro CONVST. Garante o tempo de aquisicao
    // (240 ns) mesmo quando uma captura comeca logo depois da anterior; so
    // afeta o quadro descartado, mas assim o tempo vale por construcao.
    localparam ESPERA_INICIAL = 8'd16;

    reg [31:0]          periodo;    // divisor travado no start, no minimo DIV_MIN
    reg [31:0]          fase;       // 0 .. periodo-1 dentro do quadro
    reg [16:0]          n_alvo;     // n_amostras travado, em [1, PROFUNDIDADE]
    reg                 modo_cont;  // continuo travado no start
    reg                 descartar;  // o quadro em curso e o primeiro (descartado)
    reg [ADDR_BITS-1:0] idx;        // proximo endereco da RAM (da a volta sozinho)
    reg [11:0]          palavra;    // {config, 6'b0}, enviada MSB primeiro

    // motor serial
    reg        lendo;
    reg [3:0]  nbit;           // 0..11
    reg [7:0]  sub;            // 0 .. 2*SCLK_MEIO-1 dentro do bit
    reg [11:0] shift;

    always @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            estado      <= S_IDLE;
            done        <= 1'b0;
            contador    <= 32'd0;
            adc_convst  <= 1'b0;
            adc_sclk    <= 1'b0;
            adc_din     <= 1'b0;
            ram_address <= {ADDR_BITS{1'b0}};
            ram_wdata   <= 32'd0;
            ram_write   <= 1'b0;
            periodo     <= DIV_MIN;
            fase        <= 32'd0;
            n_alvo      <= 17'd1;
            modo_cont   <= 1'b0;
            descartar   <= 1'b1;
            idx         <= {ADDR_BITS{1'b0}};
            palavra     <= 12'd0;
            lendo       <= 1'b0;
            nbit        <= 4'd0;
            sub         <= 8'd0;
            shift       <= 12'd0;
        end else begin
            ram_write <= 1'b0;
            // a amostra entra na RAM nesta borda: o contador sobe junto
            if (ram_write) contador <= contador + 32'd1;

            case (estado)
            // -----------------------------------------------------------------
            S_IDLE: begin
                done       <= 1'b0;
                adc_convst <= 1'b0;
                adc_sclk   <= 1'b0;
                adc_din    <= 1'b0;
                if (start_pulse) begin
                    periodo <= (divisor < DIV_MIN) ? DIV_MIN : divisor;
                    if (n_amostras == 16'd0)
                        n_alvo <= 17'd1;
                    else if ({1'b0, n_amostras} > PROFUNDIDADE)
                        n_alvo <= PROFUNDIDADE;
                    else
                        n_alvo <= {1'b0, n_amostras};
                    modo_cont <= continuo;
                    palavra   <= {config_adc, 6'b0};
                    fase      <= 32'd0;
                    descartar <= 1'b1;
                    idx       <= {ADDR_BITS{1'b0}};
                    contador  <= 32'd0;
                    lendo     <= 1'b0;
                    sub       <= 8'd0;
                    estado    <= S_PREP;
                end
            end

            // -----------------------------------------------------------------
            S_PREP: begin
                if (sub == ESPERA_INICIAL) begin
                    sub    <= 8'd0;
                    estado <= S_CAPT;
                end else begin
                    sub <= sub + 8'd1;
                end
            end

            // -----------------------------------------------------------------
            S_CAPT: begin
                // contador de periodo: e ele que fixa o instante das amostras
                if (fase == periodo - 1) fase <= 32'd0;
                else                     fase <= fase + 32'd1;

                if (fase == 32'd0)
                    adc_convst <= 1'b1;
                if (fase == T_CONV)
                    adc_convst <= 1'b0;

                if (fase == INICIO_LEITURA) begin
                    lendo    <= 1'b1;
                    nbit     <= 4'd0;
                    sub      <= 8'd0;
                    adc_sclk <= 1'b0;
                    adc_din  <= palavra[11];
                end

                if (lendo) begin
                    if (sub == SCLK_MEIO - 1) begin
                        adc_sclk <= 1'b1;
                        shift    <= {shift[10:0], adc_dout};
                    end
                    if (sub == 2 * SCLK_MEIO - 1) begin
                        sub      <= 8'd0;
                        adc_sclk <= 1'b0;
                        if (nbit == 4'd11) begin
                            lendo   <= 1'b0;
                            adc_din <= 1'b0;
                            // fim do quadro: guarda a amostra (menos a do quadro 0)
                            if (descartar) begin
                                descartar <= 1'b0;
                            end else begin
                                ram_address <= idx;
                                ram_wdata   <= {20'd0, shift};
                                ram_write   <= 1'b1;
                                idx         <= idx + 1'b1;
                            end
                            // fim da captura: unica, na n-esima amostra; continua,
                            // no primeiro fim de quadro depois de start baixar
                            if (modo_cont ? !start
                                          : (!descartar && contador + 32'd1 == {15'd0, n_alvo}))
                                estado <= S_DONE;
                        end else begin
                            nbit    <= nbit + 4'd1;
                            adc_din <= palavra[10 - nbit];
                        end
                    end else begin
                        sub <= sub + 8'd1;
                    end
                end
            end

            // -----------------------------------------------------------------
            S_DONE: begin
                adc_convst <= 1'b0;
                adc_sclk   <= 1'b0;
                adc_din    <= 1'b0;
                done       <= 1'b1;
                // Ao voltar ao repouso o contador zera: em S_IDLE ele vale 0
                // sempre. Assim o HPS nunca le o contador da captura anterior
                // logo depois de subir o start (o zeramento no start_pulse
                // chega uns ciclos depois da escrita no PIO, e a leitura
                // seguinte poderia passar na frente).
                if (!start) begin
                    estado   <= S_IDLE;
                    contador <= 32'd0;
                end
            end

            default: estado <= S_IDLE;
            endcase
        end
    end

endmodule
