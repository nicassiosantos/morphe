# Sinais de teste: arquivo e processamento por blocos

Arquivos para testar o tipo **Arquivo** do painel de sinal e a convolução de sinais
maiores que o hardware (1024 amostras), que a janela divide em blocos. Gerados por
`Python/ferramentas/gera_sinais_exemplo.py`.

| arquivo | o que é |
|---|---|
| `duas_senoides_8k.wav` | x[n]: 1 s a 8 kHz (8000 amostras), tom de **300 Hz** (amplitude 0,5) + tom de **3 kHz** (amplitude 0,3) |
| `duas_senoides_8k.csv` | o mesmo sinal em texto, colunas `t` e `x`, 3000 amostras |
| `passa_baixa_1k.csv` | h[n]: passa-baixa de 67 coeficientes, corte em 1 kHz |
| `impulso_atrasado.txt` | h[n] = δ[n − 2000]: 2001 amostras, também maior que o hardware |

## Como testar

No aplicativo, abra **Convolução**:

1. Em **Sinal x[n]**: Tipo → **Arquivo** → **Escolher arquivo…** → `duas_senoides_8k.wav` → **Gerar**.
2. Em **Sinal h[n]**: Tipo → **Arquivo** → `passa_baixa_1k.csv` → **Gerar**.
3. **Convoluir na FPGA.**

## O que tem de aparecer

| x[n] | h[n] | blocos | y[n] |
|---|---|---|---|
| `duas_senoides_8k.wav` | `passa_baixa_1k.csv` | 8 ("Bloco k de 8") | 8066 amostras; **só o tom de 300 Hz**, amplitude ~0,50 — a oscilação rápida do de 3 kHz some |
| `duas_senoides_8k.csv` | `passa_baixa_1k.csv` | 3 | 3066 amostras, o mesmo efeito |
| `duas_senoides_8k.wav` | `impulso_atrasado.txt` | até 16 (os blocos de h só com zeros não vão à placa) | 10000 amostras: **o próprio x, deslocado 2000 amostras** |

Conferido contra a placa `172.16.230.24` em 23/09/2026: os dois primeiros casos com
relação sinal-erro de ~59 dB contra `np.convolve`; o terceiro idêntico.

Para ver o espectro antes e depois, salve o bundle e abra no **Comparador**, ou use o
teste automático:

```bash
cd Python && python3 ferramentas/testa_blocos.py --placa 172.16.230.24
```
