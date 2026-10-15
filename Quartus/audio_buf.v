// =============================================================================
// audio_buf.v -- o audio do codec (audio_i2s.v) entrando e saindo da RAM adc_buf,
// para o HPS: captura, reproducao e loopback (etapa 3 do codec, 15/10/2026).
//
// Usa a MESMA RAM (adc_buf, 32768 palavras) e os MESMOS PIOs do ADC: nao sobra
// PIO livre no Qsys, e acrescentar um exigiria regenerar o soc_system. Quem
// escolhe e o bit 31 do adc_divisor (o divisor do ADC vai no maximo a 50 000):
// com ele em 1, o ghrd_top.v liga a RAM, o start, o done e o contador a este
// bloco, e o adc_captura nao ve o start.
//
// Uma palavra da RAM por quadro estereo: {direito[31:16], esquerdo[15:0]},
// complemento de dois de 16 bits. fs = 48 828,125 Hz, a do audio_i2s.v. O
// ritmo e o rx_quadro: o codec e mestre dos relogios e o ADC e o DAC dele
// andam juntos (o mesmo LRCK), entao um quadro recebido = um quadro enviado.
//
// Operacoes (adc_config[1:0]), com adc_config[6] = continuo:
//   0 CAPTURA            entrada do codec -> RAM
//   1 REPRODUZ           RAM -> saida do codec
//   2 CAPTURA + LOOPBACK entrada -> RAM e entrada -> saida
//   3 LOOPBACK           entrada -> saida, sem RAM
// Mesmo aperto de mao do adc_captura.v: borda de subida do start dispara.
//   unico (continuo = 0): n_amostras quadros; done sobe no fim e fica ate o
//     HPS baixar o start;
//   continuo (continuo = 1): a RAM e circular (endereco = i mod 2^ADDR_BITS)
//     e a operacao segue ate o HPS baixar o start. O LOOPBACK e sempre assim.
// `contador` = quadros ja gravados (captura) ou ja tocados (reproducao). Sobe
// no mesmo ciclo em que a RAM grava; em repouso vale 0. Na reproducao
// continua o HPS reabastece a RAM atras do contador.
//
// Fora de uma operacao a saida e silencio (tx = 0). O tom de teste da SW9
// continua no audio_i2s.v e tem prioridade sobre tudo.
// =============================================================================

module audio_buf #(
    parameter ADDR_BITS = 15
) (
    input  wire                 clk,
    input  wire                 reset_n,

    // PIOs (os do ADC, no modo audio)
    input  wire                 start,
    output reg                  done,
    input  wire [1:0]           op,
    input  wire                 continuo,
    input  wire [15:0]          n_amostras,
    output reg  [31:0]          contador,

    // audio_i2s.v
    input  wire [15:0]          rx_esq,
    input  wire [15:0]          rx_dir,
    input  wire                 rx_quadro,
    output reg  [15:0]          tx_esq,
    output reg  [15:0]          tx_dir,

    // RAM adc_buf, porta da FPGA (leitura com 1 ciclo de latencia)
    output reg  [ADDR_BITS-1:0] ram_address,
    output reg  [31:0]          ram_wdata,
    output reg                  ram_write,
    input  wire [31:0]          ram_readdata
);

localparam OP_CAPTURA = 2'd0, OP_REPRODUZ = 2'd1, OP_CAP_LOOP = 2'd2, OP_LOOP = 2'd3;
localparam S_REPOUSO = 2'd0, S_ATIVO = 2'd1, S_FIM = 2'd2;

reg [1:0]  estado;
reg        start_d;
reg [1:0]  op_r;
reg        cont_r;
reg [15:0] n_r;
reg [31:0] prox;        // reproducao: a proxima palavra, ja lida da RAM
reg [1:0]  le;          // reproducao: ciclos ate a leitura da RAM valer

wire grava    = (op_r == OP_CAPTURA) || (op_r == OP_CAP_LOOP);
wire repassa  = (op_r == OP_CAP_LOOP) || (op_r == OP_LOOP);
wire [31:0] cont_mais = contador + 32'd1;

always @(posedge clk or negedge reset_n)
    if (!reset_n) begin
        estado      <= S_REPOUSO;
        start_d     <= 1'b0;
        done        <= 1'b0;
        contador    <= 32'd0;
        op_r        <= 2'd0;
        cont_r      <= 1'b0;
        n_r         <= 16'd0;
        prox        <= 32'd0;
        le          <= 2'd0;
        tx_esq      <= 16'd0;
        tx_dir      <= 16'd0;
        ram_address <= {ADDR_BITS{1'b0}};
        ram_wdata   <= 32'd0;
        ram_write   <= 1'b0;
    end else begin
        start_d   <= start;
        ram_write <= 1'b0;

        // captura: o contador sobe no ciclo em que a RAM grava (ram_write
        // em 1 agora = a palavra entra na RAM nesta borda), e o done da
        // captura unica so sobe com a ultima palavra ja la dentro
        if (ram_write && estado == S_ATIVO) begin
            contador <= cont_mais;
            if (!cont_r && cont_mais == {16'd0, n_r}) begin
                done   <= 1'b1;
                estado <= S_FIM;
            end
        end

        // leitura da RAM em curso (reproducao): o dado vale 2 ciclos depois
        if (le != 2'd0) begin
            le <= le - 2'd1;
            if (le == 2'd1) prox <= ram_readdata;
        end

        case (estado)
        S_REPOUSO: begin
            done     <= 1'b0;
            contador <= 32'd0;
            tx_esq   <= 16'd0;
            tx_dir   <= 16'd0;
            if (start && !start_d) begin
                op_r        <= op;
                cont_r      <= continuo || (op == OP_LOOP);
                n_r         <= n_amostras;
                ram_address <= {ADDR_BITS{1'b0}};
                le          <= 2'd2;            // ja pede a palavra 0
                estado      <= S_ATIVO;
            end
        end

        S_ATIVO: begin
            if (!start) begin
                // o HPS encerrou (continuo ou loopback): volta ao silencio
                estado <= S_REPOUSO;
            end else if (rx_quadro && !ram_write) begin
                if (!cont_r && op_r == OP_REPRODUZ && contador == {16'd0, n_r}) begin
                    // reproducao unica: os n quadros ja tocaram
                    tx_esq <= 16'd0;
                    tx_dir <= 16'd0;
                    done   <= 1'b1;
                    estado <= S_FIM;
                end else begin
                    if (repassa) begin
                        tx_esq <= rx_esq;
                        tx_dir <= rx_dir;
                    end
                    if (grava) begin
                        ram_address <= contador[ADDR_BITS-1:0];
                        ram_wdata   <= {rx_dir, rx_esq};
                        ram_write   <= 1'b1;
                    end
                    if (op_r == OP_REPRODUZ) begin
                        tx_esq      <= prox[15:0];
                        tx_dir      <= prox[31:16];
                        ram_address <= cont_mais[ADDR_BITS-1:0];
                        le          <= 2'd2;
                    end
                    if (op_r == OP_REPRODUZ) contador <= cont_mais;
                end
            end
        end

        S_FIM: begin
            tx_esq <= 16'd0;
            tx_dir <= 16'd0;
            if (!start) estado <= S_REPOUSO;
        end

        default: estado <= S_REPOUSO;
        endcase
    end

endmodule
