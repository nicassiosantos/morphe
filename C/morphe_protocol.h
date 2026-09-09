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
 *   uint16 opcode   (1=CONV, 2=FFT)
 *   uint16 dtype    (1=int32, 2=float32)
 *   uint16 flags    (0)
 *   uint32 n_x      (comprimento de x)
 *   uint32 n_h      (comprimento de h; 0 para FFT)
 *
 * Response header (20 bytes):
 *   uint32 magic    = 0x4D52504E ('MRPN')
 *   uint16 version  = 1
 *   uint16 opcode   (espelha o request)
 *   uint16 dtype    (dtype do payload de saida)
 *   uint16 status   (0 = OK)
 *   uint32 n_out    (no. de amostras; para erro: bytes da msg)
 *   uint32 extra    (0)
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

#define MORPHE_HEADER_SIZE 20

#endif /* MORPHE_PROTOCOL_H */
