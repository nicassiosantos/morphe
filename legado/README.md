# legado/

Arquivos do projeto original que **o produto não usa**. Saíram de `C/`, `Python/`,
`Quartus/` e da raiz em 23/09/2026, para que essas pastas contenham só o que roda.
Ficam aqui, e não apagados, porque o estágio evolui a base existente sem substituí-la
— e porque alguns explicam decisões antigas.

| arquivo | por que não é usado |
|---|---|
| `C/morphe_server_handling_sigs.c` | cópia antiga do servidor; o `Makefile` só compila `C/morphe_server.c`, e esta não recebeu a IFFT (`docs/RESSALVAS.md`, item 7) |
| `Python/fixed_point.py` | nenhum módulo o importa; a conversão de ponto fixo mora em `dsp_core.py` |
| `Quartus/morphe_fft_wrapper.v` | não está no projeto e nada o instancia; o wrapper em uso é `Quartus/fft_wrapper.v` |
| `Quartus/deploy.sh` | versão original do envio do servidor; a em uso é o `deploy.sh` da raiz, que também envia o `morphe_config.h` |
| `Quartus/c5_pin_model_dump.txt` | arquivo gerado pelo Quartus numa compilação antiga |
| `quartus_flow.sh`, `quartus_clean.sh` | automação genérica de compilação, que nenhum script ou documento usa |

Os arquivos daqui não estão na pasta do projeto do Quartus nem no `sys.path` do
aplicativo, então não podem ser usados por engano.
