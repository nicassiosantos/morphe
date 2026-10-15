// tb_audio_i2s.v -- testbench do audio_i2s.v com um modelo do WM8731 em modo mestre.
//
// O modelo gera BCLK (3,125 MHz) e LRCK por conta propria, com fase qualquer em
// relacao aos 50 MHz da FPGA, como na placa. Ele manda palavras conhecidas pelo
// ADCDAT no formato I2S e decodifica o que a FPGA devolve pelo DACDAT.
//
// Confere:
//   1. rx_esq/rx_dir trazem as palavras enviadas, quadro a quadro;
//   2. loopback (tom = 0): o DAC recebe as mesmas palavras, com atraso fixo;
//   3. tom (tom = 1): o DAC recebe +-4096 trocando de sinal a cada 24 quadros.
//
// Rodar (de Quartus/):
//   iverilog -g2005 -o tb_audio testbench/tb_audio_i2s.v audio_i2s.v
//   vvp tb_audio
`timescale 1ns/1ps

module tb_audio_i2s;

reg clk = 0;
always #10 clk = ~clk;              // 50 MHz
reg reset_n = 0;
reg tom = 0;

// --- modelo do codec ----------------------------------------------------------
reg bclk = 0;
reg lrck = 0;
reg adcdat = 0;
wire dacdat, xck;
wire [15:0] rx_esq, rx_dir;
wire rx_quadro;

audio_i2s dut (
    .clk(clk), .reset_n(reset_n),
    .aud_xck(xck), .aud_bclk(bclk), .aud_adclrck(lrck), .aud_daclrck(lrck),
    .aud_adcdat(adcdat), .aud_dacdat(dacdat),
    .tom(tom), .tx_esq_in(lb_esq), .tx_dir_in(lb_dir),
    .rx_esq(rx_esq), .rx_dir(rx_dir), .rx_quadro(rx_quadro)
);

// loopback como o audio_buf.v faz na operacao LOOPBACK: copia o quadro
// recebido no pulso rx_quadro
reg [15:0] lb_esq = 0, lb_dir = 0;
always @(posedge clk) if (rx_quadro) begin lb_esq <= rx_esq; lb_dir <= rx_dir; end

localparam NQ = 200;
reg [15:0] env_esq [0:NQ-1];
reg [15:0] env_dir [0:NQ-1];
reg [15:0] dac_esq [0:NQ-1];
reg [15:0] dac_dir [0:NQ-1];

integer q;          // quadro do modelo
integer k;          // descidas desde a troca do LRCK
integer n;          // subidas desde a troca do LRCK
reg [15:0] palavra, dac_sh;
integer erros = 0;

initial begin
    for (q = 0; q < NQ; q = q + 1) begin
        env_esq[q] = (q * 16'h1357) ^ 16'h8001;
        env_dir[q] = ~((q * 16'h0F0F) + 16'h4321);
        dac_esq[q] = 16'hxxxx;
        dac_dir[q] = 16'hxxxx;
    end
end

// BCLK de 320 ns, com fase deslocada de 7,3 ns em relacao ao clk
initial begin
    #7.3;
    forever #160 bclk = ~bclk;
end

// lado do codec: LRCK e ADCDAT mudam na descida; DACDAT e lido na subida
initial begin
    q = 0; k = 0; n = 0;
    palavra = 0; dac_sh = 0;
    @(negedge bclk);
    while (q < NQ) begin
        // inicio de um canal: troca do LRCK nesta descida
        #8 lrck = (lrck == 0);         // atraso tipico (manual: ate 10 ns)
        palavra = (lrck == 0) ? env_esq[q] : env_dir[q];
        for (k = 0; k < 32; k = k + 1) begin
            if (k > 0) @(negedge bclk);
            // bit 16-k na descida k (k = 1..16)
            if (k >= 1 && k <= 16) #20 adcdat = palavra[16 - k];
            else                   #20 adcdat = 0;
            // subida seguinte: n = k + 1
            @(posedge bclk);
            n = k + 1;
            if (n >= 2 && n <= 17) dac_sh = {dac_sh[14:0], dacdat};
            if (n == 17) begin
                if (lrck == 0) dac_esq[q] = dac_sh;
                else           dac_dir[q] = dac_sh;
            end
        end
        @(negedge bclk);
        if (lrck == 1) q = q + 1;      // direito fecha o quadro
    end
end

// --- 1. recepcao ----------------------------------------------------------------
integer qr = -1;
integer n_rx = 0;      // quadros conferidos na recepcao
always @(posedge clk) if (rx_quadro) begin
    // o quadro que acabou de fechar e o q atual do modelo (q ainda nao avancou)
    // o quadro 0 comeca antes de o reset soltar: o esquerdo dele se perde
    qr = q;
    if (qr >= 1) n_rx = n_rx + 1;
    if (qr >= 1 && (rx_esq !== env_esq[qr] || rx_dir !== env_dir[qr])) begin
        erros = erros + 1;
        if (erros < 10)
            $display("ERRO rx quadro %0d: esq %h (esperado %h)  dir %h (esperado %h)",
                     qr, rx_esq, env_esq[qr], rx_dir, env_dir[qr]);
    end
end

// --- 2. loopback e 3. tom ---------------------------------------------------------
integer i, d, achou, q_tom, trocas, ultimo, conta, ruins;
initial begin
    #1000 reset_n = 1;
    wait (q == 100);
    // loopback: achar o atraso pelo quadro 50 e conferir 20..99 com ele
    achou = 0;
    for (d = 0; d < 5; d = d + 1)
        if (!achou && dac_esq[50] === env_esq[50 - d] && dac_dir[50] === env_dir[50 - d]) begin
            achou = 1;
            $display("loopback: atraso de %0d quadro(s)", d);
            for (i = 20; i < 100; i = i + 1)
                if (dac_esq[i] !== env_esq[i - d] || dac_dir[i] !== env_dir[i - d]) begin
                    erros = erros + 1;
                    if (erros < 10)
                        $display("ERRO loopback quadro %0d: %h %h (esperado %h %h)",
                                 i, dac_esq[i], dac_dir[i], env_esq[i-d], env_dir[i-d]);
                end
        end
    if (!achou) begin
        erros = erros + 1;
        $display("ERRO loopback: DAC nao repete o ADC (quadro 50: %h %h)", dac_esq[50], dac_dir[50]);
    end

    // tom
    tom = 1;
    q_tom = q + 3;
    wait (q == NQ - 1);
    trocas = 0; ultimo = 0; conta = 0; ruins = 0;
    for (i = q_tom; i < NQ - 1; i = i + 1) begin
        if (dac_esq[i] !== 16'd4096 && dac_esq[i] !== 16'hF000) begin ruins = ruins + 1; $display("tom q%0d: %h %h", i, dac_esq[i], dac_dir[i]); end
        if (dac_esq[i] !== dac_dir[i]) ruins = ruins + 1;
        if (i > q_tom && dac_esq[i] !== dac_esq[i-1]) begin
            if (trocas > 0 && conta != 24) begin
                ruins = ruins + 1;
                $display("ERRO tom: meio periodo de %0d quadros (esperado 24)", conta);
            end
            trocas = trocas + 1;
            conta = 0;
        end
        conta = conta + 1;
    end
    if (trocas < 3) begin ruins = ruins + 1; $display("ERRO tom: so %0d trocas de sinal", trocas); end
    if (ruins) $display("ERRO tom: %0d quadros errados", ruins);
    else       $display("tom: +-4096, %0d trocas a cada 24 quadros", trocas);
    erros = erros + ruins;

    if (n_rx < NQ - 3) begin erros = erros + 1; $display("ERRO rx: so %0d quadros recebidos", n_rx); end
    if (erros == 0) $display("TUDO OK: recepcao (%0d quadros), loopback e tom", n_rx);
    else            $display("FALHOU: %0d erro(s)", erros);
    $finish;
end

initial begin
    #(NQ * 20500 + 100000);
    $display("FALHOU: tempo esgotado (q = %0d)", q);
    $finish;
end

endmodule
