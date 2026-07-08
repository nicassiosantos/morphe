# Figuras vetoriais das telas do Morphe

Dois arquivos novos. **Nenhuma alteração no Morphe.** Solte os dois na
mesma pasta dos outros módulos.

| arquivo | o que é |
|---|---|
| `morphe_export.py` | exportador genérico Tk/ttk → SVG. Não conhece o Morphe; recebe qualquer `Toplevel` e emite vetor. |
| `gerar_figuras.py` | roda o Morphe de verdade, popula as 8 janelas e chama o exportador. |

## Como funciona

Não é screenshot. O exportador percorre a árvore de widgets da janela
**rodando**, lê a geometria que o Tk calculou (`winfo_rootx`, `winfo_width`,
`ttk.Style.lookup`, métricas de fonte) e reemite tudo como `<rect>` e
`<text>`. Onde há um gráfico, ele pega a `Figure` do Matplotlib e manda o
**backend SVG redesenhá-la do zero** — curvas, marcadores e ticks saem como
path vetorial, não como pixels ampliados.

A geometria vem do app em execução, não de um chute. É por isso que a
fidelidade é estrutural e não uma reconstrução aproximada.

## Uso

```bash
# figuras do artigo — dados vindos da FPGA
python gerar_figuras.py --host 192.168.1.10

# iterar no layout sem a placa na mesa
python gerar_figuras.py --emular

# só algumas telas; fundo branco nos gráficos (impressão)
python gerar_figuras.py --host 192.168.1.10 --so fft,conv --fundo-branco
```

Saída em `figuras/*.svg`. Para o LaTeX:

```bash
for f in figuras/*.svg; do rsvg-convert -f pdf -o "${f%.svg}.pdf" "$f"; done
# ou: inkscape --export-type=pdf figuras/*.svg
```

```latex
\includegraphics[width=\columnwidth]{figuras/morphe-fft.pdf}
```

O PDF sai com DejaVu Sans embutida e texto extraível — dá zoom infinito e
imprime nítido em qualquer resolução.

## Os dois modos, e por que a distinção importa

`--host` fala com o servidor real no DE1-SoC. Os números nos gráficos vêm
da FPGA. **Use este para o artigo e para a defesa.**

`--emular` responde aos mesmos pacotes de 20 bytes que o servidor C, com a
mesma aritmética de ponto fixo (Q15.16 na conv/FIR, com o produto indo a
int64 e voltando com shift de 16; Q15.8 na entrada da FFT). O que ele *não*
reproduz é o arredondamento interno do block floating point do FFT II — por
isso as figuras saem com sufixo `-emulado`, para você não confundir na hora
de escrever a legenda.

## O que foi verificado

O exportador foi rodado contra o Morphe real sob um X virtual, e cada SVG
foi comparado pixel a pixel com um screenshot X11 da **mesma** janela:

| janela | divergência estrutural |
|---|---|
| hub | 0,000 % |
| gerador | 0,002 % |
| convolução | 0,000 % |
| fft | 0,000 % |
| fir | 0,051 % |
| projetista fir | 0,002 % |
| comparador | 0,001 % |
| discovery | 0,000 % |

(fração de pixels de área lisa que divergem — ou seja, widget faltando, cor
errada ou geometria fora do lugar. Zero em quase tudo.)

O alinhamento do texto dentro dos botões foi medido à parte, comparando a
caixa do texto no screenshot e no vetor, botão por botão nas 6 janelas que
têm botões: **Δy = 0,0 px em todos os 20**, e Δx ≤ 0,5 px em 19 deles. O
único com Δx = 2 px ("Salvar bundle (.mrph)…") não está deslocado — a string
sai 10 px mais larga no rasterizador de SVG do que no Tk, porque o Tk usa
advance width com *hinting* (arredondado a inteiro) e o SVG usa fracionário.
O texto continua centrado; só ocupa um pouco mais de espaço. No PDF, que é o
que vai pro LaTeX, o traçado sem hinting é o correto.

O resto da diferença entre as duas imagens é antialiasing: o Tk renderiza
texto com **subpixel** (aquelas franjas coloridas de LCD), o SVG renderiza
em tons de cinza. Na impressão o vetor é o certo — franja colorida em papel
é defeito.

## Duas coisas que apareceram no caminho

**1. A toolbar do Matplotlib nunca aparece na janela de FFT.** A figura pede
800 px de altura (`figsize=(7,8), dpi=100`) e sobram ~760 no `plot_area`, então
o `pack` esmaga o `tb_frame` a 1 px e ele fica sem mapear. Não é bug do
exportador — ele só desenha o que está mapeado, e reproduziu a realidade.
Se você quiser a toolbar de volta, reduza a figura para `figsize=(7, 7)` ou
troque o `expand=True` do canvas por um `pack` com `side="top"` + `tb_frame`
antes dele.

**2. `conv_window._on_convolve` lê `self.dtype_var.get()` de dentro da thread
worker.** Passa no app normal porque o `mainloop()` está rodando e o Tkinter
enfileira a chamada; mas é uma chamada Tk fora da thread principal, que é
exatamente o que o Tkinter pede para não fazer. O jeito seguro é ler a
variável *antes* de criar a thread, junto com `x_padded`/`h_padded`:

```python
dtype_out = self.dtype_var.get()          # ← lido na thread Tk
def worker():
    ...
    dtype_out=dtype_out,
```

(É por isso que o `gerar_figuras.py` chama tudo de dentro de um
`after()` no `mainloop()`, e não antes dele.)

## Limitações honestas

* Estados de hover/foco não são desenhados — a janela sai em repouso, que é
  o que se quer numa figura. Estado `disabled` **é** respeitado (o botão
  "Aplicar FIR" sai cinza antes de você carregar os coeficientes).
* Os relevos 3D de 1 px do clam viram borda plana. A largura da borda é
  fiel (2 px — medida, não deduzida do `lookup`, que mente e diz 1).
* Se você trocar de tema ttk (sair do `clam`), as cores de fallback do
  `Entry`/`Combobox` precisam ser reconferidas.

## Sobre a legenda no artigo

Reconstrução vetorial de interface é prática comum em artigos de ferramentas,
mas a legenda deve dizer o que é. Algo como:

> Figura N — Interface do módulo de FFT do Morphe Toolkit (representação
> vetorial da tela). O espectro exibido é o resultado retornado pela FPGA
> para uma senoide de 50 Hz amostrada a 1 kHz.

Se um revisor abrir o PDF e o texto da "captura" for selecionável, é melhor
que a legenda já tenha sido franca. E a figura fica *mais* legível na coluna
do IEEE do que uma captura seria.
