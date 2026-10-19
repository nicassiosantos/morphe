/*
 * morphe_protocol.h -- constantes e layouts do protocolo Morphe-TCP.
 *
 * Este arquivo e o espelho em C do morphe_protocol.py do host.
 * Tudo em network byte order (big-endian).
 *
 * Os limites/tamanhos do hardware ficam em morphe_config.h (incluido
 * abaixo). Aqui estao apenas as definicoes do protocolo de fio.
 *
 * Request header (20 bytes):
 *   uint32 magic    = 0x4D52504D ('MRPM')
 *   uint16 version  = 1
 *   uint16 opcode   (1=CONV, 2=FFT, 3=PING, 4=FIR, 5=IFFT, 6=IIR, 7=ADC,
 *                    8=ADC_CONTINUO)
 *   uint16 dtype    (1=int32, 2=float32)
 *   uint16 flags    (0)
 *   uint32 n_x      (comprimento de x)
 *   uint32 n_h      (comprimento de h; 0 para FFT/IFFT; no IIR, o
 *                    NUMERO DE SECOES de 2a ordem)
 *
 * Payload do request, por opcode:
 *   CONV/FIR -> n_x amostras de x, seguidas de n_h amostras de h
 *   FFT      -> n_x amostras REAIS   (int32 Q15.8), 4 bytes cada
 *   IFFT     -> n_x amostras COMPLEXAS (int32 Q15.8), 8 bytes cada,
 *               re e im intercalados: re[0] im[0] re[1] im[1] ...
 *               A IFFT recebe um espectro, que e complexo por natureza;
 *               dai o payload dobrar em relacao a FFT.
 *   IIR      -> n_x amostras de x (int32 Q15.16), seguidas de 5*n_h
 *               coeficientes (int32 Q15.16), na ordem b0 b1 b2 a1 a2
 *               por secao -- a mesma da SRAM iir_coef e do
 *               iir_design.coeficientes_inteiros(). a0 = 1 implicito.
 *               Com flags = MORPHE_IIR_FLAG_ESTADO, seguem ainda 4*n_h
 *               palavras do estado inicial (ver a flag, abaixo).
 *   ADC      -> sem payload. n_x = numero de amostras, n_h = divisor
 *               (fs = 50 MHz / n_h), flags = palavra de configuracao do
 *               LTC2308 (6 bits: S/D O/S S1 S0 UNI SLP). A resposta traz
 *               n_x codigos int32 do conversor: 0..4095 em modo unipolar,
 *               -2048..2047 em bipolar (1 LSB = 1 mV); extra = divisor.
 *   ADC_CONTINUO -> igual ao ADC, mas n_x = total de amostras sem o limite
 *               da RAM (0 = ate o cliente parar). A resposta e diferente:
 *               o cabecalho (status OK, n_out = 0, extra = divisor) e depois
 *               uma sequencia de BLOCOS, enquanto a captura segue:
 *                   uint32 n       amostras neste bloco
 *                   uint32 estado  0 = segue; 1 = fim; 2 = perdeu amostras
 *                                  (o servidor nao acompanhou); 3 = timeout
 *                   n x int32      codigos, como no ADC
 *               O ultimo bloco tem n = 0 e estado != 0. Os blocos sao
 *               continuos no tempo; com estado 2, o que veio antes vale.
 *               Para parar antes, o cliente manda 1 byte qualquer (ou fecha
 *               a conexao).
 *
 * Response header (20 bytes):
 *   uint32 magic    = 0x4D52504E ('MRPN')
 *   uint16 version  = 1
 *   uint16 opcode   (espelha o request)
 *   uint16 dtype    (dtype do payload de saida)
 *   uint16 status   (0 = OK)
 *   uint32 n_out    (no. de amostras; para erro: bytes da msg)
 *   uint32 extra    (0; no IIR, 1 se alguma amostra saturou -- o
 *                    resultado vem mesmo assim, saturado, nao errado)
 */
#ifndef MORPHE_PROTOCOL_H
#define MORPHE_PROTOCOL_H

#include <stdint.h>

#include "morphe_config.h"   /* tamanhos/limites do hardware */

#define MORPHE_MAGIC_REQ   0x4D52504DU   /* 'MRPM' */
#define MORPHE_MAGIC_RESP  0x4D52504EU   /* 'MRPN' */
#define MORPHE_VERSION     1U

#define MORPHE_OP_CONV     1U
#define MORPHE_OP_FFT      2U
#define MORPHE_OP_PING     3U   /* descoberta de servico */
#define MORPHE_OP_FIR      4U   /* filtro FIR (igual ao OP_FIR=4 do cliente) */
#define MORPHE_OP_IFFT     5U   /* transformada inversa: mesmo IP, bit inverse=1 */
#define MORPHE_OP_IIR      6U   /* cascata de biquads Q15.16 (iir_cascade.v) */
#define MORPHE_OP_ADC      7U   /* captura do LTC2308 a fs fixa (adc_captura.v) */
#define MORPHE_OP_ADC_CONTINUO 8U   /* a mesma, sem limite de tamanho, em blocos */
#define MORPHE_OP_AUDIO    9U   /* codec de audio: captura, reproducao, loopback */

/* Suboperacoes do OP_AUDIO, no campo `flags` do cabecalho.
 *   CAPTURA   n_x = quadros (0 = ate o cliente parar), n_h bit 0 = com loopback;
 *             resposta em blocos, como o ADC_CONTINUO.
 *   REPRODUZ  n_x = quadros, que seguem o cabecalho em int32 {dir, esq};
 *             resposta: cabecalho com n_out = n_x e extra = estado do fim.
 *   LOOPBACK  n_h = 1 liga, 0 desliga; fica ligado entre conexoes.
 *   AO_VIVO   captura filtrada pelo bloco IIR da placa, em tempo real, sem
 *             bitstream novo: n_x = quadros (0 = ate parar), n_h = secoes
 *             (1 a 16); seguem 1 + 5*n_h int32: o aquecimento (amostras, ate
 *             896) e os coeficientes Q15.16. Resposta em blocos, como a
 *             captura, com cada palavra {saida filtrada, entrada}. */
/* Flag do OP_IIR, no campo `flags` do cabecalho.
 *   ESTADO  o payload traz, depois dos coeficientes, o estado inicial:
 *           4*n_h int32 (x1 x2 y1 y2 por secao, Q15.16); so dtype int32.
 *           A resposta traz n_out = n_x + 4*n_h: y e depois o estado final
 *           (o estado depois das MORPHE_IIR_N_MAX amostras do bloco), e
 *           extra bit 1 = 1. Com um bitstream que nao devolve o estado,
 *           extra bit 1 = 0 e so y vem (n_out = n_x) -- valido so se o
 *           estado inicial era zero; se nao era, a resposta e erro. */
#define MORPHE_IIR_FLAG_ESTADO     1U
#define MORPHE_IIR_EXTRA_SATUROU   1U
#define MORPHE_IIR_EXTRA_ESTADO    2U

#define MORPHE_AUDIO_CAPTURA   0U
#define MORPHE_AUDIO_REPRODUZ  1U
#define MORPHE_AUDIO_LOOPBACK  2U
#define MORPHE_AUDIO_AO_VIVO   4U

/* Estado de cada bloco da resposta do ADC_CONTINUO. */
#define MORPHE_ADC_BLOCO_SEGUE    0U
#define MORPHE_ADC_BLOCO_FIM      1U
#define MORPHE_ADC_BLOCO_PERDEU   2U
#define MORPHE_ADC_BLOCO_TIMEOUT  3U

#define MORPHE_DTYPE_INT32    1U
#define MORPHE_DTYPE_FLOAT32  2U

#define MORPHE_STATUS_OK              0U
#define MORPHE_STATUS_BAD_MAGIC       1U
#define MORPHE_STATUS_BAD_VERSION     2U
#define MORPHE_STATUS_BAD_OPCODE      3U
#define MORPHE_STATUS_BAD_DTYPE       4U
#define MORPHE_STATUS_BAD_SIZE        5U
#define MORPHE_STATUS_FPGA_TIMEOUT    6U
#define MORPHE_STATUS_INTERNAL_ERROR  7U
/* A FPGA ainda esta com o bitstream de fabrica (placa recem-ligada); o
 * morphe-up.sh ainda nao programou o do Morphe nesta placa. */
#define MORPHE_STATUS_FPGA_NAO_PREPARADA 8U

#define MORPHE_HEADER_SIZE 20

#endif /* MORPHE_PROTOCOL_H */
