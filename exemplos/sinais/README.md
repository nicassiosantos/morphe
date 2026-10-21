# Sinais de teste: arquivo e FFT longa

Arquivos para testar a entrada por arquivo e a FFT de sinais maiores que o hardware
(1024 amostras). Gerados por `Python/ferramentas/gera_sinais_exemplo.py`.

| arquivo | o que é |
|---|---|
| `duas_senoides_8k.wav` | x[n]: 1 s a 8 kHz (8000 amostras), tom de **300 Hz** (amplitude 0,5) + tom de **3 kHz** (amplitude 0,3) |
| `duas_senoides_8k.csv` | o mesmo sinal em texto, colunas `t` e `x`, 3000 amostras |

## FFT

1. **Sinal x[n]** → Tipo **Arquivo** → **Escolher arquivo…** → `duas_senoides_8k.wav` → **Gerar**
2. **Calcular FFT na FPGA** → FFT de **8192 pontos** em quatro passos (8 FFTs de 1024 na
   placa); picos em 300 Hz e 3 kHz
3. **Salvar tudo (x, X) em 1 arquivo .mrph** → abra no **Comparador** para ver o erro
   contra o NumPy

## Gerador de sinais

Tipo **Arquivo** → qualquer um dos arquivos acima → **Gerar**. Sinais longos aparecem
como linha, e podem ser salvos em `.mrph`.

## Teste automático

```bash
cd Python && python3 ferramentas/testa_blocos.py --placa 172.16.230.24
```
