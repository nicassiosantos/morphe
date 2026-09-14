# relatorio_timing.tcl -- extrai o Fmax e os piores caminhos, que o fluxo
# padrao de compilacao NAO escreve no soc_system.sta.rpt.
#
# O .sta.rpt gerado pelo 'Start Compilation' traz apenas os resumos: ele diz
# que o pior slack e -0,364 e em qual relogio, mas nao diz ENTRE QUAIS NOS.
# Sem isso nao da para saber o que corrigir, e cada palpite errado custa uma
# compilacao inteira.
#
# Uso, com o Quartus FECHADO (interface e linha de comando brigam pelo lock
# do db/ e a analise falha com Error 23031):
#
#     cd ~/Documentos/validacao-final/morphe/Quartus
#     quartus_sta -t relatorio_timing.tcl
#
# Escreve output_files/timing_resumo.txt.

project_open soc_system -revision soc_system

create_timing_netlist
read_sdc
update_timing_netlist

set saida "output_files/timing_resumo.txt"

# Fmax de cada relogio. E este numero que diz se o projeto fecha a 50 MHz.
report_clock_fmax_summary -file $saida

# Resumo por relogio: qual viola e por quanto.
report_timing -setup -npaths 1 -detail summary -file $saida -append

# Os piores caminhos do relogio principal, com no de origem e de destino.
# E aqui que se descobre se o gargalo e o divisor do iir_cascade, o
# acumulador do iir_biquad_mac, ou outra coisa.
if {[catch {
    report_timing -setup -npaths 15 -detail path_only \
                  -to_clock clock_50_1 -file $saida -append
} erro]} {
    post_message -type warning "filtro por clock_50_1 falhou ($erro); relatando todos"
    report_timing -setup -npaths 15 -detail path_only -file $saida -append
}

# Os piores caminhos do projeto inteiro, sem filtro de relogio, como rede de
# seguranca caso o gargalo esteja num dominio que nao esperavamos.
report_timing -setup -npaths 15 -detail path_only -file $saida -append

post_message "pronto: Quartus/output_files/timing_resumo.txt"

project_close
