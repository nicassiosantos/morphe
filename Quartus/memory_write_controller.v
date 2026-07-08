module memory_write_controller #(
	parameter MEM_ADDRESS_N_BITS = 5,
	parameter DATA_WIDTH = 32
)(
	input wire clk,
	input wire reset_n,
	input wire start_write,
	input wire [MEM_ADDRESS_N_BITS-1:0] data_in_addr,
	input wire [DATA_WIDTH-1:0] data_in,
	
	output reg [MEM_ADDRESS_N_BITS-1:0] mem_address,
	output reg [DATA_WIDTH-1:0] mem_wdata,
	output reg mem_write,
	output reg write_done,
	output reg clken,
	output reg chipselect
);
	
	// Estados da maquina
	localparam IDLE           = 2'b_00;
	localparam PREPARE_WRITE  = 2'b_01;
	localparam WRITE_ACTIVE   = 2'b_10; 
	localparam DONE           = 2'b_11;

	reg [1:0] sram_state; // Removida a inicialização aqui, será feita pelo Reset

	always @ (posedge clk or negedge reset_n) begin
		if(!reset_n) begin
			// --- Reset Assíncrono ---
			sram_state  <= IDLE;
			mem_wdata   <= {DATA_WIDTH{1'b_0}};
			mem_address <= {MEM_ADDRESS_N_BITS{1'b_0}};
			mem_write   <= 1'b_0;
			write_done  <= 1'b_0;
			clken       <= 1'b_0;
			chipselect  <= 1'b_0;
			
		end
		else begin
			// --- Lógica de Atribuição Padrão (Default Assignment) ---
			// Sinais de controlo são LOW/OFF por default
			mem_write  <= 1'b_0; 
            write_done <= 1'b_0;
			case (sram_state)
				IDLE: begin
						if(start_write) begin
							sram_state <= PREPARE_WRITE;
							write_done <= 1'b_0;
							clken <= 1'b_1;
							chipselect <= 1'b_1;
						end
						// Note: read_done já é LOW pelo default assignment
				end
				
				PREPARE_WRITE: begin
					// 1. Aplica Endereço e Dado
					mem_address <= data_in_addr;
					mem_wdata   <= data_in;
					
					// 2. Ativa o pulso de escrita (Ciclo 1)
					mem_write <= 1'b_1;
					
					// 3. Transiciona IMEDIATAMENTE.
					sram_state <= DONE;
				end
				
				DONE: begin
					// 1. Sinaliza a conclusão neste ciclo.
					write_done <= 1'b_1;
					chipselect <= 1'b_0;
					clken <= 1'b_0;
					// 2. Retorna ao estado inicial.
					sram_state <= IDLE;
					// Note: mem_write já é LOW pelo Default Assignment.
				end
				
				default: begin
					sram_state <= IDLE;
				end
			endcase
		end
	end
endmodule