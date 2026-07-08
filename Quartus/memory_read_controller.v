module memory_read_controller #(
    parameter DATA_WIDTH = 32,
    parameter MEM_ADDRESS_N_BITS = 5
)(
    input wire                          clk,
    input wire                          reset_n,
    input wire                          start_read,
    input wire[DATA_WIDTH-1:0]          sram_readdata,
    input wire[MEM_ADDRESS_N_BITS-1:0]  data_addr,
    
	output reg                          mem_write,
    output reg[DATA_WIDTH-1:0]          data_out,
    output reg[MEM_ADDRESS_N_BITS-1:0]  mem_address,
    output reg                          read_done,
    output reg                          clken,
    output reg                          chipselect
);

    localparam IDLE = 3'b_000;
    localparam PREPARE_READ = 3'b_001;
    localparam SAMPLE_DATA = 3'b_011;
    localparam DONE = 3'b_111;
    
    reg [2:0] sram_state = IDLE;
	
    // reset assincrono
    always @ (posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            sram_state <= IDLE;
            read_done <= 1'b_0;
            mem_write <= 1'b_0;
            data_out <= {DATA_WIDTH{1'b_0}};
            mem_address <= {MEM_ADDRESS_N_BITS{1'b_0}};
            clken <= 1'b_0;
            chipselect <= 1'b_0;
        end
        else begin
            case (sram_state)
                IDLE: begin
                    if(start_read) begin
                        sram_state <= PREPARE_READ;
                        clken <= 1'b_1;
                        chipselect <= 1'b_1;
                    end
                    read_done <= 1'b_0;
                end

                PREPARE_READ: begin
                    //mem_rdata <= sram_readdata;
                    mem_address <= data_addr;
                    mem_write <= 1'b_0;
                    sram_state <= SAMPLE_DATA;
                end

                SAMPLE_DATA: begin
                    data_out <= sram_readdata;
                    sram_state <= DONE;
                end

                DONE: begin
                    clken <= 1'b_0;
                    chipselect <= 1'b_0;
                    read_done <= 1'b_1;
                    sram_state <= IDLE;
                end

                default: sram_state <= IDLE;
            endcase
        end
    end
endmodule