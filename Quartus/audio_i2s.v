// =============================================================================
// audio_i2s.v -- interface I2S com o codec WM8731 da DE1-SoC (etapa 2 do codec).
//
// Quem gera os relogios de audio e o CODEC (modo mestre, R7 = 0x042: I2S,
// 16 bits, MS = 1). A FPGA so entrega o relogio-mestre AUD_XCK e le BCLK e
// LRCK como entradas, amostrando tudo a 50 MHz. Assim o projeto inteiro
// continua num dominio de relogio so, como o adc_captura.v.
//
// AUD_XCK = 50 MHz / 4 = 12,5 MHz, de um contador -- sem PLL. Com o codec em
// modo normal, 256 fs (R8 = 0x000), a taxa fica
//     fs = 12,5 MHz / 256 = 48 828,125 Hz   (exata: 50e6 / 1024)
// e BCLK = 64 fs = 3,125 MHz (manual do WM8731, "Master mode": BCLK = 64x a
// taxa base). Sao 16 ciclos de 50 MHz por ciclo de BCLK: folga para os
// sincronizadores. Para 48 000 Hz exatos seria preciso um PLL fracionario
// (12,288 MHz); para o laboratorio a taxa exata e conhecida basta.
//
// Formato I2S (manual do WM8731, "I2S mode"): o LRCK muda na descida do BCLK
// (0 = canal esquerdo, 1 = direito); o MSB fica disponivel na 2a SUBIDA do
// BCLK depois da troca do LRCK; os dados mudam na descida e sao lidos na
// subida. Com 32 BCLK por canal e palavra de 16 bits, os 16 restantes sao 0.
//
// Contagem usada aqui: `n` = numero de subidas do BCLK desde a troca do LRCK
// (a primeira subida com o LRCK novo vale n = 1).
//   recepcao (ADCDAT): bits nas subidas n = 2..17, MSB primeiro.
//   envio    (DACDAT): bit (16 - n) posto na descida seguinte a subida n,
//                      para n = 1..16; fora disso, 0.
// A troca do LRCK e vista na SUBIDA (ele mudou na descida anterior e ja esta
// estavel), nunca na descida em que muda -- ali haveria corrida.
//
// Fonte do DAC (`tom`):
//   0 = loopback digital: o que entra pela LINE-in volta pela LINE-out,
//       atrasado um quadro (o caminho passa pela FPGA, prova recepcao e envio);
//   1 = onda quadrada gerada aqui, +-4096 (-18 dBFS), trocando a cada 24
//       quadros: 48 828 / 48 = 1017 Hz. Prova o DAC sem fonte de audio.
//
// Saidas rx_*: a ultima amostra estereo recebida e um pulso por quadro --
// o ponto de onde a captura para a RAM (etapa 3) vai ler.
// =============================================================================

module audio_i2s (
    input  wire        clk,          // 50 MHz
    input  wire        reset_n,

    // pinos do WM8731
    output wire        aud_xck,      // relogio-mestre do codec, 12,5 MHz
    input  wire        aud_bclk,     // gerado pelo codec (mestre)
    input  wire        aud_adclrck,  // gerado pelo codec
    input  wire        aud_daclrck,  // gerado pelo codec
    input  wire        aud_adcdat,   // codec -> FPGA
    output reg         aud_dacdat,   // FPGA -> codec

    input  wire        tom,          // 1 = onda quadrada de teste no DAC

    // ultima amostra recebida (complemento de dois)
    output reg  [15:0] rx_esq,
    output reg  [15:0] rx_dir,
    output reg         rx_quadro     // 1 ciclo: rx_esq/rx_dir de um quadro novo
);

// --- relogio-mestre: 50 / 4 ---------------------------------------------------
reg [1:0] div_xck;
always @(posedge clk or negedge reset_n)
    if (!reset_n) div_xck <= 2'd0;
    else          div_xck <= div_xck + 2'd1;
assign aud_xck = div_xck[1];

// --- sincronizadores ----------------------------------------------------------
// BCLK e ADCDAT passam pelo MESMO numero de estagios, para que o dado lido na
// subida detectada seja o do instante dessa subida.
reg [2:0] bclk_s;
reg [1:0] adcdat_s;
reg [1:0] adclrc_s;
reg [1:0] daclrc_s;
always @(posedge clk or negedge reset_n)
    if (!reset_n) begin
        bclk_s   <= 3'b000;
        adcdat_s <= 2'b00;
        adclrc_s <= 2'b00;
        daclrc_s <= 2'b00;
    end else begin
        bclk_s   <= {bclk_s[1:0], aud_bclk};
        adcdat_s <= {adcdat_s[0], aud_adcdat};
        adclrc_s <= {adclrc_s[0], aud_adclrck};
        daclrc_s <= {daclrc_s[0], aud_daclrck};
    end

wire bclk_sobe  =  bclk_s[1] & ~bclk_s[2];
wire bclk_desce = ~bclk_s[1] &  bclk_s[2];
wire adc_bit    = adcdat_s[1];
wire adclrc     = adclrc_s[1];
wire daclrc     = daclrc_s[1];

// --- recepcao (ADCDAT) --------------------------------------------------------
reg        rx_lrc_ant;
reg [5:0]  rx_n;
reg [15:0] rx_sh;

always @(posedge clk or negedge reset_n)
    if (!reset_n) begin
        rx_lrc_ant <= 1'b0;
        rx_n       <= 6'd63;     // so comeca a contar depois da 1a troca de LRCK
        rx_sh      <= 16'd0;
        rx_esq     <= 16'd0;
        rx_dir     <= 16'd0;
        rx_quadro  <= 1'b0;
    end else begin
        rx_quadro <= 1'b0;
        if (bclk_sobe) begin
            if (adclrc != rx_lrc_ant) begin
                rx_lrc_ant <= adclrc;
                rx_n       <= 6'd1;
            end else if (rx_n != 6'd63) begin
                rx_n <= rx_n + 6'd1;
                // esta e a subida rx_n+1
                if (rx_n >= 6'd1 && rx_n <= 6'd16) begin
                    rx_sh <= {rx_sh[14:0], adc_bit};
                    if (rx_n == 6'd16) begin
                        if (adclrc == 1'b0) begin
                            rx_esq <= {rx_sh[14:0], adc_bit};
                        end else begin
                            rx_dir    <= {rx_sh[14:0], adc_bit};
                            rx_quadro <= 1'b1;   // direito fecha o quadro
                        end
                    end
                end
            end
        end
    end

// --- fonte do DAC -------------------------------------------------------------
// Loopback: copia a amostra recebida. Tom: +-4096 trocando a cada 24 quadros.
reg        tx_lrc_ant;     // LRCK do DAC visto na ultima subida (bloco de envio)
reg [5:0]  tx_n;
reg [15:0] tx_sh;
reg [4:0]  tom_cont;
reg        tom_fase;
reg [15:0] tx_esq, tx_dir;

always @(posedge clk or negedge reset_n)
    if (!reset_n) begin
        tom_cont <= 5'd0;
        tom_fase <= 1'b0;
        tx_esq   <= 16'd0;
        tx_dir   <= 16'd0;
    end else if (tom) begin
        // o tom anda no ritmo do LRCK do DAC: uma troca para o DIREITO = um quadro.
        // Trocar a fase ali (e nao no esquerdo) faz o envio do direito, que carrega
        // nessa mesma subida, ainda pegar a fase velha: os dois canais de um quadro
        // saem sempre com o mesmo sinal.
        if (bclk_sobe && daclrc != tx_lrc_ant && daclrc == 1'b1) begin
            if (tom_cont == 5'd23) begin
                tom_cont <= 5'd0;
                tom_fase <= ~tom_fase;
            end else begin
                tom_cont <= tom_cont + 5'd1;
            end
        end
        tx_esq <= tom_fase ? 16'sd4096 : -16'sd4096;
        tx_dir <= tom_fase ? 16'sd4096 : -16'sd4096;
    end else if (rx_quadro) begin
        tx_esq <= rx_esq;
        tx_dir <= rx_dir;
    end

// --- envio (DACDAT) -----------------------------------------------------------
always @(posedge clk or negedge reset_n)
    if (!reset_n) begin
        tx_lrc_ant <= 1'b0;
        tx_n       <= 6'd63;
        tx_sh      <= 16'd0;
        aud_dacdat <= 1'b0;
    end else begin
        if (bclk_sobe) begin
            if (daclrc != tx_lrc_ant) begin
                // subida n = 1 do canal novo: carrega a palavra dele
                tx_lrc_ant <= daclrc;
                tx_n       <= 6'd1;
                tx_sh      <= daclrc ? tx_dir : tx_esq;
            end else if (tx_n != 6'd63) begin
                tx_n <= tx_n + 6'd1;
            end
        end
        if (bclk_desce) begin
            // descida depois da subida n: bit 16-n (MSB em n = 1)
            if (tx_n >= 6'd1 && tx_n <= 6'd16) begin
                aud_dacdat <= tx_sh[15];
                tx_sh      <= {tx_sh[14:0], 1'b0};
            end else begin
                aud_dacdat <= 1'b0;
            end
        end
    end

endmodule
