# Decisões do estágio

Registro curto das decisões tomadas, com a data, para apoiar o relatório final. Ele
substitui as atas formais previstas no plano: o acompanhamento com o supervisor é
diário e presencial, no próprio laboratório, e as decisões abaixo foram tomadas nesse
acompanhamento, de acordo com as orientações do Prof. Armando S. Sanca.

O que foi feito e medido em cada dia está no `DIARIO.md`. Aqui fica só **o que foi
decidido e por quê**; quando o motivo não foi registrado na hora, a coluna diz só quem
pediu.

| data | decisão | motivo |
|---|---|---|
| 01–03/09 | Linha de base de usabilidade medida **só em número de passos**, sem tempo e sem sujeitos | o tempo depende de quem executa; a contagem de passos é reproduzível (`LINHA-DE-BASE-PASSOS.md`) |
| 14/09 | Manter a **truncação do `conv1d.v`** como o autor escreveu, sem trocar por arredondamento | preservar a base existente; registrado como escolha em `RESSALVAS.md`, item 3 |
| 14/09 | Teto de **100 arquivos `.mrph` por operação** gravados na placa | cartão SD cheio falha longe da causa |
| 15/09 | Bloco IIR mesclado na principal **só depois de testado na interface** | não levar à turma o que só passou em teste isolado |
| 17/09 | **Sem serviço systemd** na estação para preparar as placas; fica o comando explícito `morphe-up.sh` | um serviço no boot falharia calado com a placa desligada ou fora da rede |
| 22/09 | **Interface aprovada** como está: encerra a v1.3 (biblioteca) e a v1.6 (interface) do plano | decisão do supervisor |
| 22/09 | Nova frente: Morphe **e** Quartus em todos os PCs do laboratório; levantar o ADC e o codec da placa; manual do sistema em LaTeX (Overleaf) | definida junto com a aprovação da interface |
| 23/09 | Início oficial do estágio em **25/09/2026**, encerramento em 09/12/2026 | ajuste dos documentos; plano revisado e assinado |
| 23/09 | **ADC primeiro**, Morphe nos outros PCs depois | decisão do estagiário |
| 23/09 | Janela de **espectrograma fora do menu** (arquivo mantido, três linhas comentadas) | a pedido |
| 24/09 | ADC com **controlador próprio**, um canal por captura, fs de 1 a 200 kHz, até 32 768 amostras | o IP do University Program não tem instante de amostragem definido (`ADC.md`) |
| 24/09 | Gráfico de espectro **desligado** na janela Aquisição | a pedido; religar só se pedido |
| 24/09 | Manual em português, classe `report`, figuras em TikZ, público = professor, monitor e quem for estender o sistema | tomada na escrita dos caps. 1–3 e não contestada |
| 28/09 | **Porta de estado UDP** nas placas (livre/ocupada) e escolha automática da placa livre e menos usada | primeira parte da v1.4 sem trocar o servidor de lugar |
| 28/09 | Captura contínua do ADC **sem limite de duração** | escolha na definição dos modos de captura (o Parar guarda o que veio) |
| 28/09 | Lista de placas versionada (`placas.conf`) **e** varredura da rede, as duas juntas | a lista é rápida; a varredura acha placas novas |
| 28/09 | Codec de áudio **fora do texto do manual** | a pedido |
| 30/09 | **Sem reserva de DHCP** junto à TI; placas achadas por **broadcast** e pelo nome | resolve o IP variável sem depender de terceiros |
| 01/10 | Analisador espectral **linear (volts de pico), com o espectro completo** de 0 a fs | a pedido ("não quero dB", "espectro completo") |
| 01/10 | Roteiros **práticos**: um diagrama por etapa, no formato Faça / Confira | o roteiro longo foi recusado |
| 05/10 | Roteiro de módulo: o aluno cria o módulo e **testa sozinho pela serial antes de integrar**; o porquê de cada passo explicado; código completo no PDF; nenhum número fixo de cabo ou porta | isolar o erro de hardware do erro de integração |
| 05/10 | "Soquete de módulo" aceito como ideia, **para depois**, quando pedido | não abrir outra frente antes de validar o primeiro roteiro |
| 07/10 | Roteiro da convolução: o aluno escreve só o `conv_aluno.v` e compara com o `conv1d`; teoria própria, sem artigo; teste no app | foco no módulo, não na infraestrutura |
| 07/10 | Gabarito da convolução em branch **local, sem push** | o repositório é público; o gabarito ficaria visível aos alunos |
| 08/10 | Roteiro da convolução **sem testbench** | correção pedida ao seguir o roteiro no laboratório |
| 13/10 | Codec de áudio: configuração **pelo HPS** (I2C0), codec como mestre dos relógios, relógio-mestre de **12,5 MHz sem PLL** (fs = 48 828,125 Hz) | dispensa controlador I2C na FPGA e mantém um só domínio de relógio |
| 13/10 | **Sem atas formais**; este arquivo registra as decisões | o acompanhamento com o supervisor é diário e presencial |
| 15/10 | **Arredondar** no `conv1d.v` (convolução e FIR) em vez de truncar: soma em 64 bits (Q32.32) e um arredondamento só, na saída; revoga a decisão de 14/09 | pedido do Antonio; o erro máximo contra a conta exata cai de 539,6 para 0,5 LSB com N = 1024 (simulado) |
