// Testbench do soma_core: os mesmos casos da tabela da Parte A do roteiro
// (docs/roteiro-modulo). Valores em Q15.16: hex = valor * 65536.
// Rodar, de dentro de Quartus/:
//   iverilog -o tb_soma_core.vvp testbench/tb_soma_core.v soma_core.v
//   vvp tb_soma_core.vvp
`timescale 1 ns / 1 ps
module tb_soma_core;
    reg  [31:0] a, b;
    wire [31:0] y;
    integer erros = 0;

    soma_core dut (.a(a), .b(b), .y(y));

    task caso(input [31:0] va, input [31:0] vb, input [31:0] esperado, input [8*28-1:0] nome);
        begin
            a = va; b = vb; #10;
            if (y === esperado)
                $display("ok    %s  a=%h b=%h y=%h", nome, a, b, y);
            else begin
                $display("ERRO  %s  a=%h b=%h y=%h (esperado %h)", nome, a, b, y, esperado);
                erros = erros + 1;
            end
        end
    endtask

    initial begin
        caso(32'h00018000, 32'h00024000, 32'h0003C000, "1,5 + 2,25 = 3,75");
        caso(32'hFFFF0000, 32'h00008000, 32'hFFFF8000, "-1 + 0,5 = -0,5");
        caso(32'h00640000, 32'hFF9C0000, 32'h00000000, "100 + (-100) = 0");
        caso(32'h00000001, 32'h00000001, 32'h00000002, "menor fracao + menor fracao");
        caso(32'h75300000, 32'h75300000, 32'h7FFFFFFF, "30000 + 30000 satura em +");
        caso(32'h8AD00000, 32'h8AD00000, 32'h80000000, "-30000 + -30000 satura em -");
        if (erros == 0) $display("TUDO OK");
        else            $display("%0d ERRO(S)", erros);
        $finish;
    end
endmodule
