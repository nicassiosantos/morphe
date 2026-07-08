// `timescale 1ns / 1ps
module  (
    // Relógio principal do sistema
    input wire clk,
    // Reset assíncrono (ativo em nível baixo)
    input wire reset_n,
    // Sinal para iniciar a sequência de escrita
    input wire write_start,
    
    // Interface com a SRAM
    output reg [4:0] onchip_sram_s1_address,
    output reg onchip_sram_s1_clken,
    output reg onchip_sram_s1_chipselect,
    output reg onchip_sram_s1_write,
    input wire [31:0] onchip_sram_s1_readdata, // Nao utilizada neste modulo
    output reg [31:0] onchip_sram_s1_writedata,
    output reg [3:0] onchip_sram_s1_byteenable,
    
    // Sinal de status para indicar que a escrita foi concluida
    output reg write_sequence_done
);
    
    // ====================================================================
    // 1. Definicao dos Estados da Maquina de Estados Finito (FSM)
    // ====================================================================
    // Estados possiveis para o processo de escrita
    localparam [1:0] 
        S_IDLE = 2'b00,        // Estado de espera, aguardando o sinal de inicio
        S_WRITE_LOOP = 2'b01,  // Estado de loop, onde a escrita ocorre em cada ciclo
        S_DONE = 2'b10;        // Estado de conclusao, sinaliza o termino
    
    // Registrador de estado atual
    reg [1:0] state;
    
    // ====================================================================
    // 2. Registradores Internos
    // ====================================================================
    // Contador de endereco para percorrer todas as posicoes de memoria
    reg [4:0] address_counter;
    
    // ====================================================================
    // 3. Logica Sincrona (Transicoes de Estado e Atualizacao de Registradores)
    // ====================================================================
    always @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            // Reinicializa todos os registradores ao estado padrao
            state <= S_IDLE;
            address_counter <= 5'd0;
            onchip_sram_s1_address <= 5'd0;
            onchip_sram_s1_writedata <= 32'h0;
            onchip_sram_s1_clken <= 1'b0;
            onchip_sram_s1_chipselect <= 1'b0;
            onchip_sram_s1_write <= 1'b0;
            onchip_sram_s1_byteenable <= 4'b0000;
            write_sequence_done <= 1'b0;
        end else begin
            // Logica de transicao de estado
            case (state)
                S_IDLE: begin
                    // Aguarda o sinal de inicio.
                    if (write_start) begin
                        state <= S_WRITE_LOOP;
                        // Resetamos o contador para comecar do inicio da memoria
                        address_counter <= 5'd0;
                        write_sequence_done <= 1'b0;
                    end
                end
                
                S_WRITE_LOOP: begin
                    // Condicao de parada: se todos os enderecos foram escritos
                    if (address_counter == 5'd32) begin
                        state <= S_DONE;
                    end else begin
                        // Incrementa o contador para a proxima posicao de memoria
                        address_counter <= address_counter + 1'b1;
                    end
                end
                
                S_DONE: begin
                    // Mantem o estado de conclusao ate um novo reset
                    state <= S_DONE;
                end
                
                default: begin
                    // Estado invalido, retorna ao estado de espera
                    state <= S_IDLE;
                end
            endcase
        end
    end
    
    // ====================================================================
    // 4. Logica Combinacional (Sinais de Saida)
    // ====================================================================
    // A logica combinacional define o valor dos sinais de saida
    // baseada no estado atual e nos registradores internos.
    
    always @(*) begin
        // Valores padrao (seguros) para os sinais
        onchip_sram_s1_clken = 1'b0;
        onchip_sram_s1_chipselect = 1'b0;
        onchip_sram_s1_write = 1'b0;
        onchip_sram_s1_byteenable = 4'b0000;
        onchip_sram_s1_address = 5'd0;
        onchip_sram_s1_writedata = 32'h0;
        write_sequence_done = 1'b0;
        
        case (state)
            S_IDLE: begin
                // Todos os sinais de controle da RAM ficam desativados
                // O dado a ser escrito nao eh relevante neste estado
            end
            
            S_WRITE_LOOP: begin
                // Ativa os sinais de controle para uma operacao de escrita
                onchip_sram_s1_clken <= 1'b1;
                onchip_sram_s1_chipselect <= 1'b1;
                onchip_sram_s1_write <= 1'b1;
                onchip_sram_s1_byteenable <= 4'b1111; // Habilita a escrita nos 4 bytes
                
                // Define o endereco e o dado a ser escrito
                onchip_sram_s1_address <= address_counter;
                // Exemplo: escreve o valor do endereco, facilitando a verificacao
                onchip_sram_s1_writedata <= {27'b0, address_counter};
                // Outra opcao para gerar dados:
                // onchip_sram_s1_writedata <= 32'hDEADBEEF + address_counter;
            end
            
            S_DONE: begin
                // A escrita esta completa. Sinais de controle desativados
                write_sequence_done <= 1'b1; // Sinaliza a conclusao
            end
            
            default: begin
                // Estado invalido
            end
        endcase
    end

endmodule