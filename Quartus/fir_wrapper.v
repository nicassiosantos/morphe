// =============================================================================
// morphe_fir.v
//
// Wrapper para o IP FIR II (altera_fir_compiler_ii v20.1).
//
// Configuracao do IP (extraida de fir_ii.v):
//   - Single rate, simetrico, 65 taps
//   - Clock rate: 50 MHz, Input rate: 0.52 MSPS  (96 ciclos por amostra)
//   - I/O: 16 bits signed
//   - Backpressure: ON
//
// Interface de SRAM (convencao do projeto Morphe):
//   address     : endereco
//   write       : 1 = escrita, 0 = leitura
//   clken       : clock enable da porta
//   chipselect  : ativa o acesso na borda atual
//   readdata    : dado lido (porta de leitura)
//   writedata   : dado a escrever (porta de escrita)
//
// Funcionamento:
//   1. HPS aciona 'start' via PIO.
//   2. FSM emite chipselect/address na SRAM de entrada; readdata fica
//      valido 1 ciclo depois e e apresentado ao FIR via Avalon-ST.
//   3. Avalon-ST com ready_latency=0: amostra so e considerada entregue
//      quando sink_valid && sink_ready coincidem no mesmo edge.
//   4. Capturador independente escreve cada source_valid na SRAM de saida.
//   5. Drenagem por contagem real (write_idx == SAMPLE_COUNT), sem timeout.
//   6. 'done' e sticky ate o proximo 'start'.
// =============================================================================

`timescale 1 ns / 1 ps

module fir_wrapper #(
    parameter SAMPLE_COUNT  = 1024,
    parameter ADDR_WIDTH    = 10,
    parameter SAMPLE_PERIOD = 96         // 50e6 / 0.52e6
) (
    input                        clk,
    input                        rst_n,

    // Controle (HPS via PIO)
    input                        start,
    output reg                   done,
    output reg                   error,         // ast_source_error sticky

    // Porta de SRAM de entrada (somente leitura deste lado)
    output     [ADDR_WIDTH-1:0]  in_address,
    output                       in_write,      // amarrado em 0
    output                       in_clken,
    output                       in_chipselect,
    input      [15:0]            in_readdata,

    // Porta de SRAM de saida (somente escrita deste lado)
    output     [ADDR_WIDTH-1:0]  out_address,
    output                       out_write,
    output                       out_clken,
    output                       out_chipselect,
    output     [15:0]            out_writedata,

    // Debug
    output     [3:0]             state_dbg
);

    // -------------------------------------------------------------------------
    // Instanciacao do IP FIR II
    // -------------------------------------------------------------------------
    reg  [15:0] sink_data;
    reg         sink_valid;
    wire        sink_ready;

    wire [15:0] source_data;
    wire        source_valid;
    wire [1:0]  source_error;
    wire        source_ready = 1'b1;          // SRAM local sempre aceita

    fir_ii u_fir (
        .clk              (clk),
        .reset_n          (rst_n),
        .ast_sink_data    (sink_data),
        .ast_sink_valid   (sink_valid),
        .ast_sink_error   (2'b00),
        .ast_sink_ready   (sink_ready),
        .ast_source_data  (source_data),
        .ast_source_valid (source_valid),
        .ast_source_error (source_error),
        .ast_source_ready (source_ready)
    );

    // -------------------------------------------------------------------------
    // FSM
    // -------------------------------------------------------------------------
    localparam S_IDLE   = 4'd0;
    localparam S_READ   = 4'd1;     // emite address+chipselect
    localparam S_LATCH  = 4'd2;     // captura readdata e prepara sink
    localparam S_OFFER  = 4'd3;     // valid alto, espera sink_ready
    localparam S_WAIT   = 4'd4;     // honra intervalo de SAMPLE_PERIOD
    localparam S_DRAIN  = 4'd5;     // espera o pipeline drenar
    localparam S_DONE   = 4'd6;

    reg [3:0]                    state;
    reg [ADDR_WIDTH-1:0]         read_idx;
    reg [6:0]                    pause_cnt;
    reg [ADDR_WIDTH:0]           write_idx;     // 1 bit extra p/ alcancar SAMPLE_COUNT

    assign state_dbg = state;

    // -------------------------------------------------------------------------
    // Controle combinacional da SRAM de entrada
    // Convencao Quartus on-chip RAM (sync read, 1 ciclo de latencia):
    //   ciclo N:   address valido + chipselect alto
    //   ciclo N+1: readdata valido
    // -------------------------------------------------------------------------
    assign in_address    = read_idx;
    assign in_write      = 1'b0;
    assign in_clken      = 1'b1;
    assign in_chipselect = (state == S_READ);

    // -------------------------------------------------------------------------
    // FSM principal (lado de entrada)
    // -------------------------------------------------------------------------
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state      <= S_IDLE;
            read_idx   <= {ADDR_WIDTH{1'b0}};
            sink_data  <= 16'd0;
            sink_valid <= 1'b0;
            pause_cnt  <= 7'd0;
            done       <= 1'b0;
        end else begin
            case (state)

                // ------------------------------------------------------------
                S_IDLE: begin
                    sink_valid <= 1'b0;
                    if (start) begin
                        done     <= 1'b0;
                        read_idx <= {ADDR_WIDTH{1'b0}};
                        state    <= S_READ;
                    end
                end

                // ------------------------------------------------------------
                S_READ: begin
                    // chipselect e address ja drivados combinacionalmente
                    state <= S_LATCH;
                end

                // ------------------------------------------------------------
                S_LATCH: begin
                    // readdata agora reflete SRAM[read_idx]
                    sink_data  <= in_readdata;
                    sink_valid <= 1'b1;
                    pause_cnt  <= 7'd0;
                    state      <= S_OFFER;
                end

                // ------------------------------------------------------------
                S_OFFER: begin
                    // Avalon-ST ready_latency=0: transferencia ocorre quando
                    // valid && ready coincidem no mesmo edge. Mantemos
                    // sink_valid e sink_data ate isso acontecer.
                    if (sink_valid && sink_ready) begin
                        sink_valid <= 1'b0;
                        state      <= S_WAIT;
                    end
                end

                // ------------------------------------------------------------
                S_WAIT: begin
                    // Total por amostra: S_READ + S_LATCH + S_OFFER + S_WAIT
                    // Para 96 ciclos com S_OFFER tipico de 1 ciclo:
                    //   1 + 1 + 1 + N  ==  96  =>  N = 93 (pause de 0 a 92)
                    if (pause_cnt >= SAMPLE_PERIOD - 4) begin
                        if (read_idx == SAMPLE_COUNT - 1) begin
                            state <= S_DRAIN;
                        end else begin
                            read_idx <= read_idx + 1'b1;
                            state    <= S_READ;
                        end
                    end else begin
                        pause_cnt <= pause_cnt + 1'b1;
                    end
                end

                // ------------------------------------------------------------
                S_DRAIN: begin
                    // Espera o pipeline interno do FIR drenar.
                    // Criterio: contagem real de saidas capturadas.
                    if (write_idx == SAMPLE_COUNT)
                        state <= S_DONE;
                end

                // ------------------------------------------------------------
                S_DONE: begin
                    done  <= 1'b1;            // sticky ate proximo start
                    state <= S_IDLE;
                end

                default: state <= S_IDLE;
            endcase
        end
    end

    // -------------------------------------------------------------------------
    // Capturador da saida -> SRAM de saida
    //
    // Registra address/writedata/write para timing limpo. Existe 1 ciclo
    // de delay entre source_valid e a escrita efetiva, mas a integridade
    // dos dados e preservada (registros amostram source_data no mesmo edge
    // em que source_valid e detectado).
    // -------------------------------------------------------------------------
    reg [ADDR_WIDTH-1:0] out_address_r;
    reg [15:0]           out_writedata_r;
    reg                  out_write_r;

    assign out_address    = out_address_r;
    assign out_writedata  = out_writedata_r;
    assign out_write      = out_write_r;
    assign out_chipselect = out_write_r;       // ativa apenas durante escrita
    assign out_clken      = 1'b1;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            write_idx       <= {(ADDR_WIDTH+1){1'b0}};
            out_address_r   <= {ADDR_WIDTH{1'b0}};
            out_writedata_r <= 16'd0;
            out_write_r     <= 1'b0;
            error           <= 1'b0;
        end else begin
            out_write_r <= 1'b0;

            // Reset do contador no inicio de uma nova execucao
            if (state == S_IDLE && start) begin
                write_idx <= {(ADDR_WIDTH+1){1'b0}};
                error     <= 1'b0;
            end
            // Captura de saida valida
            else if (source_valid && source_ready &&
                     write_idx < SAMPLE_COUNT) begin
                out_address_r   <= write_idx[ADDR_WIDTH-1:0];
                out_writedata_r <= source_data;
                out_write_r     <= 1'b1;
                write_idx       <= write_idx + 1'b1;

                if (source_error != 2'b00)
                    error <= 1'b1;
            end
        end
    end

endmodule