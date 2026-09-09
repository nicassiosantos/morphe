/*
 * morphe_server.c — servidor TCP no HPS da DE1-SoC.
 *
 * Recebe requests do host (Python) via protocolo Morphe, executa a operação
 * na FPGA (conv1d ou FFT) acessando SRAMs/PIOs mapeados em /dev/mem, e
 * devolve o resultado pelo mesmo socket.
 *
 * Compilar: make
 * Rodar:    sudo ./morphe_server [porta]
 *
 * Requer root (mmap /dev/mem). Single-threaded — atende uma conexão por vez.
 */

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <errno.h>
#include <unistd.h>
#include <fcntl.h>
#include <time.h>
#include <math.h>

#include <sys/mman.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <arpa/inet.h>
#include <ifaddrs.h>
#include <net/if.h>

#include "morphe_protocol.h"
#include "hps_0.h"
#include "address_map_arm.h"

#define ENABLE_DEBUG_FILES 1

/* =======================================================================
 * Mmap da regiao FPGA on-chip -- tamanho derivado automaticamente do
 * hps_0.h. NAO ajustar a mao.
 * ======================================================================= */

#define _MORPHE_MAX2(a, b)              ((a) > (b) ? (a) : (b))
#define _MORPHE_MAX3(a, b, c)           _MORPHE_MAX2(_MORPHE_MAX2(a, b), c)
#define _MORPHE_MAX4(a, b, c, d)        _MORPHE_MAX2(_MORPHE_MAX2(a, b), _MORPHE_MAX2(c, d))

#define _MORPHE_END(BASE, SPAN)         ((BASE) + (SPAN))
#define _MORPHE_PAGE_SIZE               0x1000U      /* 4 KiB */
#define _MORPHE_ROUND_UP(x, m)          (((x) + (m) - 1U) & ~((m) - 1U))

#define _MORPHE_END_FFT \
    _MORPHE_MAX4( \
        _MORPHE_END(FFT_XN_RE_BASE,   FFT_XN_RE_SPAN), \
        _MORPHE_END(FFT_XN_IMAG_BASE, FFT_XN_IMAG_SPAN), \
        _MORPHE_END(FFT_YN_RE_BASE,   FFT_YN_RE_SPAN), \
        _MORPHE_END(FFT_YN_IMAG_BASE, FFT_YN_IMAG_SPAN))

#define _MORPHE_END_CONV \
    _MORPHE_MAX3( \
        _MORPHE_END(CONV1D_XN_BASE, CONV1D_XN_SPAN), \
        _MORPHE_END(CONV1D_HN_BASE, CONV1D_HN_SPAN), \
        _MORPHE_END(CONV1D_YN_BASE, CONV1D_YN_SPAN))

#define _MORPHE_END_FIR \
    _MORPHE_MAX3( \
        _MORPHE_END(FIR_XN_BASE, FIR_XN_SPAN), \
        _MORPHE_END(FIR_HN_BASE, FIR_HN_SPAN), \
        _MORPHE_END(FIR_YN_BASE, FIR_YN_SPAN))

#define MORPHE_ONCHIP_MMAP_SPAN \
    _MORPHE_ROUND_UP( \
        _MORPHE_MAX3(_MORPHE_END_FFT, _MORPHE_END_CONV, _MORPHE_END_FIR), \
        _MORPHE_PAGE_SIZE)

/* Saida maxima do FIR: derivada do span real de fir_yn no hps_0.h. */
#define MORPHE_FIR_Y_MAX  ((int)(FIR_YN_SPAN / sizeof(int32_t)))

_Static_assert(FFT_XN_RE_SPAN   >= MORPHE_FFT_N * (int)sizeof(int32_t), "Erro");
_Static_assert(FFT_XN_IMAG_SPAN >= MORPHE_FFT_N * (int)sizeof(int32_t), "Erro");
_Static_assert(FFT_YN_RE_SPAN   >= MORPHE_FFT_N * (int)sizeof(int32_t), "Erro");
_Static_assert(FFT_YN_IMAG_SPAN >= MORPHE_FFT_N * (int)sizeof(int32_t), "Erro");
_Static_assert(CONV1D_XN_SPAN   >= MORPHE_CONV_N_MAX * (int)sizeof(int32_t), "Erro");
_Static_assert(CONV1D_HN_SPAN   >= MORPHE_CONV_N_MAX * (int)sizeof(int32_t), "Erro");
_Static_assert(CONV1D_YN_SPAN   >= MORPHE_CONV_Y_MAX * (int)sizeof(int32_t), "Erro");
_Static_assert(FIR_XN_SPAN      >= MORPHE_CONV_N_MAX * (int)sizeof(int32_t), "Erro");
_Static_assert(FIR_HN_SPAN      >= MORPHE_CONV_N_MAX * (int)sizeof(int32_t), "Erro");
_Static_assert(FIR_YN_SPAN      >= MORPHE_CONV_Y_MAX * (int)sizeof(int32_t), "Erro");
_Static_assert(MORPHE_ONCHIP_MMAP_SPAN <= FPGA_ONCHIP_SPAN + 1, "Erro");

#define FPGA_DONE_TIMEOUT_MS 5000
#define RX_BUF_MAX 16384
#define TX_BUF_MAX 32768

/* =======================================================================
 * Globais — ponteiros mapeados e fd de /dev/mem
 * ======================================================================= */
static int    g_fd_mem    = -1;
static void  *g_fpga_virt = NULL;   
static void  *g_lw_virt   = NULL;   

static int32_t  *g_fft_xn_re   = NULL;
static int32_t  *g_fft_xn_imag = NULL;
static int32_t  *g_fft_yn_re   = NULL;
static int32_t  *g_fft_yn_imag = NULL;

static int32_t  *g_conv_xn    = NULL;
static int32_t  *g_conv_hn    = NULL;
static int32_t  *g_conv_yn    = NULL;

static int32_t  *g_fir_xn     = NULL;
static int32_t  *g_fir_hn     = NULL;
static int32_t  *g_fir_yn     = NULL;

static volatile uint32_t *g_pio_fft_start    = NULL;
static volatile uint32_t *g_pio_fft_inverse  = NULL;
static volatile uint32_t *g_pio_fft_done     = NULL;
static volatile uint32_t *g_pio_fft_bfp_exp  = NULL;

static volatile uint32_t *g_pio_conv_start   = NULL;
static volatile uint32_t *g_pio_conv_done    = NULL;

static volatile uint32_t *g_pio_fir_start    = NULL;
static volatile uint32_t *g_pio_fir_done     = NULL;
static volatile uint32_t *g_pio_fir_error    = NULL;

static struct timespec  g_start_time;
static char             g_hostname[128] = "morphe-server";

#define LOG(fmt, ...) do { \
    fprintf(stderr, "[morphe] " fmt "\n", ##__VA_ARGS__); \
} while (0)

/* =======================================================================
 * I/O de socket
 * ======================================================================= */

static int send_all(int sock, const void *buf, size_t len) {
    const uint8_t *p = (const uint8_t *) buf;
    size_t sent = 0;
    while (sent < len) {
        ssize_t n = send(sock, p + sent, len - sent, 0);
        if (n <= 0) {
            if (n < 0 && errno == EINTR) continue;
            return -1;
        }
        sent += (size_t) n;
    }
    return 0;
}

static int recv_exact(int sock, void *buf, size_t len) {
    uint8_t *p = (uint8_t *) buf;
    size_t got = 0;
    while (got < len) {
        ssize_t n = recv(sock, p + got, len - got, 0);
        if (n == 0) return -1;   
        if (n < 0) {
            if (errno == EINTR) continue;
            return -1;
        }
        got += (size_t) n;
    }
    return 0;
}

static uint32_t u32_from_be(const uint8_t *p) {
    uint32_t be;
    memcpy(&be, p, 4);
    return ntohl(be);
}

static void u32_to_be(uint8_t *p, uint32_t v) {
    uint32_t be = htonl(v);
    memcpy(p, &be, 4);
}

static int32_t i32_from_be(const uint8_t *p) { return (int32_t) u32_from_be(p); }
static void i32_to_be(uint8_t *p, int32_t v) { u32_to_be(p, (uint32_t) v); }

static float f32_from_be(const uint8_t *p) {
    uint32_t host_bits = u32_from_be(p);
    float f;
    memcpy(&f, &host_bits, 4);
    return f;
}

static void f32_to_be(uint8_t *p, float f) {
    uint32_t bits;
    memcpy(&bits, &f, 4);
    u32_to_be(p, bits);
}

/* =======================================================================
 * mmap e desmapeamento
 * ======================================================================= */

static int fpga_init(void) {
    g_fd_mem = open("/dev/mem", O_RDWR | O_SYNC);
    if (g_fd_mem < 0) return -1;

    g_fpga_virt = mmap(NULL, MORPHE_ONCHIP_MMAP_SPAN, PROT_READ | PROT_WRITE,
                       MAP_SHARED, g_fd_mem, FPGA_ONCHIP_BASE);
    if (g_fpga_virt == MAP_FAILED) return -1;

    g_lw_virt = mmap(NULL, LW_BRIDGE_SPAN, PROT_READ | PROT_WRITE,
                     MAP_SHARED, g_fd_mem, LW_BRIDGE_BASE);
    if (g_lw_virt == MAP_FAILED) return -1;

    g_fft_xn_re   = (int32_t *)((char *)g_fpga_virt + FFT_XN_RE_BASE);
    g_fft_xn_imag = (int32_t *)((char *)g_fpga_virt + FFT_XN_IMAG_BASE);
    g_fft_yn_re   = (int32_t *)((char *)g_fpga_virt + FFT_YN_RE_BASE);
    g_fft_yn_imag = (int32_t *)((char *)g_fpga_virt + FFT_YN_IMAG_BASE);

    g_conv_xn = (int32_t *)((char *)g_fpga_virt + CONV1D_XN_BASE);
    g_conv_hn = (int32_t *)((char *)g_fpga_virt + CONV1D_HN_BASE);
    g_conv_yn = (int32_t *)((char *)g_fpga_virt + CONV1D_YN_BASE);

    g_fir_xn = (int32_t *)((char *)g_fpga_virt + FIR_XN_BASE);
    g_fir_hn = (int32_t *)((char *)g_fpga_virt + FIR_HN_BASE);
    g_fir_yn = (int32_t *)((char *)g_fpga_virt + FIR_YN_BASE);

    g_pio_fft_start   = (volatile uint32_t *)((char *)g_lw_virt + FFT_WRAPPER_START_BASE);
    g_pio_fft_inverse = (volatile uint32_t *)((char *)g_lw_virt + FFT_INVERSE_BASE);
    g_pio_fft_done    = (volatile uint32_t *)((char *)g_lw_virt + FFT_WRAPPER_DONE_BASE);
    g_pio_fft_bfp_exp = (volatile uint32_t *)((char *)g_lw_virt + FFT_BFP_EXPONENT_BASE);

    g_pio_conv_start = (volatile uint32_t *)((char *)g_lw_virt + CONV1D_START_BASE);
    g_pio_conv_done  = (volatile uint32_t *)((char *)g_lw_virt + CONV1D_DONE_BASE);

    g_pio_fir_start  = (volatile uint32_t *)((char *)g_lw_virt + FIR_START_BASE);
    g_pio_fir_done   = (volatile uint32_t *)((char *)g_lw_virt + FIR_DONE_BASE);
    g_pio_fir_error  = (volatile uint32_t *)((char *)g_lw_virt + FIR_ERROR_BASE);

    *g_pio_fft_start  = 0;
    *g_pio_conv_start = 0;
    *g_pio_fir_start  = 0;

    LOG("FPGA mapeada. FFT_ONCHIP=%p (%u KiB)", g_fpga_virt, MORPHE_ONCHIP_MMAP_SPAN / 1024U);
    return 0;
}

static void fpga_shutdown(void) {
    if (g_fpga_virt) munmap(g_fpga_virt, MORPHE_ONCHIP_MMAP_SPAN);
    if (g_lw_virt)   munmap(g_lw_virt,   LW_BRIDGE_SPAN);
    if (g_fd_mem >= 0) close(g_fd_mem);
}

static int wait_done(volatile uint32_t *pio_done, int timeout_ms) {
    struct timespec t0, now;
    clock_gettime(CLOCK_MONOTONIC, &t0);
    while (((*pio_done) & 0x1) == 0) {
        clock_gettime(CLOCK_MONOTONIC, &now);
        long elapsed_ms = (now.tv_sec - t0.tv_sec) * 1000L + (now.tv_nsec - t0.tv_nsec) / 1000000L;
        if (elapsed_ms >= timeout_ms) return -1;
        usleep(50);
    }
    return 0;
}

static long ts_diff_us(const struct timespec *a, const struct timespec *b) {
    return (b->tv_sec  - a->tv_sec)  * 1000000L + (b->tv_nsec - a->tv_nsec) / 1000L;
}

static void build_resp_header(uint8_t hdr[MORPHE_HEADER_SIZE], uint16_t opcode, uint16_t dtype, uint16_t status, uint32_t n_out) {
    u32_to_be(hdr + 0,  MORPHE_MAGIC_RESP);
    uint16_t v;
    v = htons(MORPHE_VERSION);  memcpy(hdr + 4,  &v, 2);
    v = htons(opcode);          memcpy(hdr + 6,  &v, 2);
    v = htons(dtype);           memcpy(hdr + 8,  &v, 2);
    v = htons(status);          memcpy(hdr + 10, &v, 2);
    u32_to_be(hdr + 12, n_out);
    u32_to_be(hdr + 16, 0);     
}

static int send_error(int sock, uint16_t opcode, uint16_t status, const char *msg) {
    uint8_t hdr[MORPHE_HEADER_SIZE];
    size_t msg_len = strlen(msg);
    build_resp_header(hdr, opcode, MORPHE_DTYPE_FLOAT32, status, (uint32_t) msg_len);
    if (send_all(sock, hdr, sizeof hdr) < 0) return -1;
    if (msg_len > 0 && send_all(sock, msg, msg_len) < 0) return -1;
    LOG("  -> erro enviado: status=%u msg=\"%s\"", status, msg);
    return 0;
}

#define MORPHE_Q1508_INT_MAX  (((int32_t)1 << 23) - 1) 
#define MORPHE_Q1508_INT_MIN  (-((int32_t)1 << 23))      
#define MORPHE_Q1508_SCALE    (1 << MORPHE_FFT_FRAC_BITS)  

static int32_t saturate_q1508(int32_t v) {
    if (v >  MORPHE_Q1508_INT_MAX) return MORPHE_Q1508_INT_MAX;
    if (v <  MORPHE_Q1508_INT_MIN) return MORPHE_Q1508_INT_MIN;
    return v;
}

static int32_t saturate_int32_from_float(float f) {
    if (isnan(f)) return 0;
    if (f >= 2147483647.0f)  return INT32_MAX;
    if (f <= -2147483648.0f) return INT32_MIN;
    return (int32_t) lrintf(f);
}

static void decode_samples_to_i32(const uint8_t *buf, uint32_t n, uint16_t dtype, int32_t *out) {
    if (dtype == MORPHE_DTYPE_INT32) {
        for (uint32_t i = 0; i < n; i++) out[i] = i32_from_be(buf + i * 4);
    } else {
        for (uint32_t i = 0; i < n; i++) out[i] = saturate_int32_from_float(f32_from_be(buf + i * 4));
    }
}

static void decode_samples_to_q1508(const uint8_t *buf, uint32_t n, int32_t *out) {
    for (uint32_t i = 0; i < n; i++) out[i] = saturate_q1508(i32_from_be(buf + i * 4));
}


/* =======================================================================
 * Utilities: File Dumpers (.mrph bundles)
 * ======================================================================= */

static void save_debug_bundle_conv(const char *prefix, uint16_t dtype,
                                   uint32_t n_x, const int32_t *x,
                                   uint32_t n_h, const int32_t *h,
                                   uint32_t n_y, const int32_t *y) {
#if ENABLE_DEBUG_FILES
    time_t now = time(NULL);
    struct tm *t = localtime(&now);
    char filename[128];
    strftime(filename, sizeof(filename), "%Y%m%d_%H%M%S", t);
    
    char filepath[256];
    snprintf(filepath, sizeof(filepath), "%s_%s.mrph", prefix, filename);
    
    FILE *f = fopen(filepath, "w");
    if (!f) {
        LOG("Erro ao criar arquivo de debug %s", filepath);
        return;
    }
    
    char timestamp[64];
    strftime(timestamp, sizeof(timestamp), "%Y-%m-%d %H:%M:%S", t);
    const char *type_str = (dtype == MORPHE_DTYPE_INT32) ? "int32" : "float32";
    
    fprintf(f, "# MORPHE BUNDLE FILE\n");
    fprintf(f, "# saved: %s\n", timestamp);
    fprintf(f, "# title: %s server debug dump\n", prefix);
    fprintf(f, "# sections: 3\n");
    fprintf(f, "# section_names: x, h, y\n\n");
    
    /* Section x */
    fprintf(f, "## section: x\n");
    fprintf(f, "# type: %s\n", type_str);
    fprintf(f, "# length: %u\n", n_x);
    fprintf(f, "# columns: n value\n");
    for (uint32_t i = 0; i < n_x; i++) {
        if (dtype == MORPHE_DTYPE_FLOAT32) fprintf(f, "%u\t%.8e\n", i, (float)x[i]);
        else fprintf(f, "%u\t%d\n", i, x[i]);
    }
    fprintf(f, "\n");
    
    /* Section h */
    fprintf(f, "## section: h\n");
    fprintf(f, "# type: %s\n", type_str);
    fprintf(f, "# length: %u\n", n_h);
    fprintf(f, "# columns: n value\n");
    for (uint32_t i = 0; i < n_h; i++) {
        if (dtype == MORPHE_DTYPE_FLOAT32) fprintf(f, "%u\t%.8e\n", i, (float)h[i]);
        else fprintf(f, "%u\t%d\n", i, h[i]);
    }
    fprintf(f, "\n");
    
    /* Section y */
    fprintf(f, "## section: y\n");
    fprintf(f, "# type: %s\n", type_str);
    fprintf(f, "# length: %u\n", n_y);
    fprintf(f, "# columns: n value\n");
    for (uint32_t i = 0; i < n_y; i++) {
        if (dtype == MORPHE_DTYPE_FLOAT32) fprintf(f, "%u\t%.8e\n", i, (float)y[i]);
        else fprintf(f, "%u\t%d\n", i, y[i]);
    }
    
    fclose(f);
    LOG("  -> Debug bundle salvo em: %s", filepath);
#endif
}

static void save_debug_bundle_fft(uint32_t n_x,
                                  const int32_t *x_re_raw, const int32_t *x_im_raw,
                                  const int32_t *y_re_raw, const int32_t *y_im_raw,
                                  uint32_t exp_raw, int32_t bfp_exp,
                                  float total_scale) {
#if ENABLE_DEBUG_FILES
    time_t now = time(NULL);
    struct tm *t = localtime(&now);
    char filename[128];
    strftime(filename, sizeof(filename), "fft_%Y%m%d_%H%M%S.mrph", t);
    
    FILE *f = fopen(filename, "w");
    if (!f) {
        LOG("Erro ao criar arquivo de debug %s", filename);
        return;
    }
    
    char timestamp[64];
    strftime(timestamp, sizeof(timestamp), "%Y-%m-%d %H:%M:%S", t);
    
    fprintf(f, "# MORPHE BUNDLE FILE\n");
    fprintf(f, "# saved: %s\n", timestamp);
    fprintf(f, "# title: fft server debug dump\n");
    fprintf(f, "# sections: 3\n");
    fprintf(f, "# section_names: x, y_raw, y\n");
    fprintf(f, "# bfp_exp_raw: 0x%02X (%u)\n", exp_raw, exp_raw);
    fprintf(f, "# bfp_exp_decoded: %d\n", bfp_exp);
    fprintf(f, "# total_scale: %.8e\n", total_scale);
    fprintf(f, "# q1508_scale: %d\n\n", MORPHE_Q1508_SCALE);
    
    /* Section x: entrada (Q15.8 decodificado para float) */
    fprintf(f, "## section: x\n");
    fprintf(f, "# type: float32\n");
    fprintf(f, "# length: %u\n", n_x);
    fprintf(f, "# format: Q15.8 decoded (raw / 2^%d)\n", MORPHE_FFT_FRAC_BITS);
    fprintf(f, "# columns: n re im\n");
    for (uint32_t i = 0; i < n_x; i++) {
        float re = (float)x_re_raw[i] / (float)MORPHE_Q1508_SCALE;
        float im = (x_im_raw ? (float)x_im_raw[i] : 0.0f) / (float)MORPHE_Q1508_SCALE;
        fprintf(f, "%u\t%.8e\t%.8e\n", i, re, im);
    }
    fprintf(f, "\n");
    
    /* Section y_raw: saida bruta da FFT (inteiros, antes do scaling BFP) */
    fprintf(f, "## section: y_raw\n");
    fprintf(f, "# type: int32\n");
    fprintf(f, "# length: %u\n", n_x);
    fprintf(f, "# format: raw FFT output (before BFP scaling)\n");
    fprintf(f, "# columns: k re im\n");
    for (uint32_t k = 0; k < n_x; k++) {
        fprintf(f, "%u\t%d\t%d\n", k, y_re_raw[k], y_im_raw[k]);
    }
    fprintf(f, "\n");
    
    /* Section y: saida escalada (raw * total_scale) */
    fprintf(f, "## section: y\n");
    fprintf(f, "# type: float32\n");
    fprintf(f, "# length: %u\n", n_x);
    fprintf(f, "# format: scaled (raw * total_scale)\n");
    fprintf(f, "# columns: k re im\n");
    for (uint32_t k = 0; k < n_x; k++) {
        float re = (float)y_re_raw[k] * total_scale;
        float im = (float)y_im_raw[k] * total_scale;
        fprintf(f, "%u\t%.8e\t%.8e\n", k, re, im);
    }
    
    fclose(f);
    LOG("  -> Debug bundle salvo em: %s", filename);
#endif
}


/* =======================================================================
 * Handlers Originais com Logging Injetado
 * ======================================================================= */

static int handle_conv(int sock, uint16_t dtype, uint32_t n_x, uint32_t n_h) {
    LOG("CONV request: dtype=%u, n_x=%u, n_h=%u", dtype, n_x, n_h);

    if (n_x == 0 || n_h == 0 || n_x > MORPHE_CONV_N_MAX || n_h > MORPHE_CONV_N_MAX) {
        char msg[96];
        snprintf(msg, sizeof msg, "CONV: n_x e n_h devem estar em [1, %d]", MORPHE_CONV_N_MAX);
        return send_error(sock, MORPHE_OP_CONV, MORPHE_STATUS_BAD_SIZE, msg);
    }

    uint32_t n_out = n_x + n_h - 1;
    if (n_out > MORPHE_CONV_Y_MAX) {
        char msg[96];
        snprintf(msg, sizeof msg, "CONV: saída excede %d amostras", MORPHE_CONV_Y_MAX);
        return send_error(sock, MORPHE_OP_CONV, MORPHE_STATUS_BAD_SIZE, msg);
    }

    size_t payload_bytes = (size_t)(n_x + n_h) * 4;
    static uint8_t rx_buf[RX_BUF_MAX];
    if (payload_bytes > sizeof rx_buf) return send_error(sock, MORPHE_OP_CONV, MORPHE_STATUS_BAD_SIZE, "CONV: payload excede buffer");
    if (recv_exact(sock, rx_buf, payload_bytes) < 0) return -1;

    static int32_t x_buf[MORPHE_CONV_N_MAX];
    static int32_t h_buf[MORPHE_CONV_N_MAX];
    decode_samples_to_i32(rx_buf,           n_x, dtype, x_buf);
    decode_samples_to_i32(rx_buf + n_x * 4, n_h, dtype, h_buf);

    for (uint32_t i = 0; i < MORPHE_CONV_N_MAX; i++) g_conv_xn[i] = (i < n_x) ? x_buf[i] : 0;
    for (uint32_t i = 0; i < MORPHE_CONV_N_MAX; i++) g_conv_hn[i] = (i < n_h) ? h_buf[i] : 0;

    *g_pio_conv_start = 0;
    usleep(1);
    *g_pio_conv_start = 1;

    if (wait_done(g_pio_conv_done, FPGA_DONE_TIMEOUT_MS) < 0) {
        *g_pio_conv_start = 0;
        return send_error(sock, MORPHE_OP_CONV, MORPHE_STATUS_FPGA_TIMEOUT, "CONV: timeout");
    }
    *g_pio_conv_start = 0;

    static int32_t y_buf[MORPHE_CONV_Y_MAX];
    for (uint32_t i = 0; i < n_out; i++) y_buf[i] = g_conv_yn[i];

    /* Salva bundle de debug antes de enviar */
    save_debug_bundle_conv("conv1d", dtype, n_x, x_buf, n_h, h_buf, n_out, y_buf);

    static uint8_t tx_buf[TX_BUF_MAX];
    uint8_t hdr[MORPHE_HEADER_SIZE];
    build_resp_header(hdr, MORPHE_OP_CONV, dtype, MORPHE_STATUS_OK, n_out);

    if (dtype == MORPHE_DTYPE_INT32) {
        for (uint32_t i = 0; i < n_out; i++) i32_to_be(tx_buf + i * 4, y_buf[i]);
    } else {
        for (uint32_t i = 0; i < n_out; i++) f32_to_be(tx_buf + i * 4, (float) y_buf[i]);
    }

    if (send_all(sock, hdr, sizeof hdr) < 0) return -1;
    if (send_all(sock, tx_buf, (size_t) n_out * 4) < 0) return -1;

    LOG("  -> CONV OK: n_out=%u", n_out);
    return 0;
}

static int handle_fir(int sock, uint16_t dtype, uint32_t n_x, uint32_t n_h) {
    LOG("FIR request: dtype=%u, n_x=%u, n_h=%u", dtype, n_x, n_h);

    if (n_x == 0 || n_h == 0 || n_x > MORPHE_CONV_N_MAX || n_h > MORPHE_CONV_N_MAX) {
        char msg[96];
        snprintf(msg, sizeof msg, "FIR: limites [1, %d]", MORPHE_CONV_N_MAX);
        return send_error(sock, MORPHE_OP_FIR, MORPHE_STATUS_BAD_SIZE, msg);
    }

    uint32_t n_out = n_x + n_h - 1;
    if (n_out > (uint32_t) MORPHE_FIR_Y_MAX) {
        char msg[96];
        snprintf(msg, sizeof msg, "FIR: saída acima da memória fir_yn (%d amostras)", MORPHE_FIR_Y_MAX);
        return send_error(sock, MORPHE_OP_FIR, MORPHE_STATUS_BAD_SIZE, msg);
    }

    size_t payload_bytes = (size_t)(n_x + n_h) * 4;
    static uint8_t rx_buf[RX_BUF_MAX];
    if (payload_bytes > sizeof rx_buf) return send_error(sock, MORPHE_OP_FIR, MORPHE_STATUS_BAD_SIZE, "FIR: payload excedido");
    if (recv_exact(sock, rx_buf, payload_bytes) < 0) return -1;

    static int32_t x_buf[MORPHE_CONV_N_MAX];
    static int32_t h_buf[MORPHE_CONV_N_MAX];
    decode_samples_to_i32(rx_buf,           n_x, dtype, x_buf);
    decode_samples_to_i32(rx_buf + n_x * 4, n_h, dtype, h_buf);

    for (uint32_t i = 0; i < MORPHE_CONV_N_MAX; i++) g_fir_xn[i] = (i < n_x) ? x_buf[i] : 0;
    for (uint32_t i = 0; i < MORPHE_CONV_N_MAX; i++) g_fir_hn[i] = (i < n_h) ? h_buf[i] : 0;

    *g_pio_fir_start = 0;
    usleep(1);
    *g_pio_fir_start = 1;

    if (wait_done(g_pio_fir_done, FPGA_DONE_TIMEOUT_MS) < 0) {
        *g_pio_fir_start = 0;
        return send_error(sock, MORPHE_OP_FIR, MORPHE_STATUS_FPGA_TIMEOUT, "FIR: timeout");
    }
    *g_pio_fir_start = 0;

    int fir_error = (int) (*g_pio_fir_error & 0x1U);

    static int32_t y_buf[MORPHE_CONV_Y_MAX];
    for (uint32_t i = 0; i < n_out; i++) y_buf[i] = g_fir_yn[i];

    /* Salva bundle de debug */
    save_debug_bundle_conv("fir", dtype, n_x, x_buf, n_h, h_buf, n_out, y_buf);

    static uint8_t tx_buf[TX_BUF_MAX];
    uint8_t hdr[MORPHE_HEADER_SIZE];
    uint16_t status = fir_error ? MORPHE_STATUS_INTERNAL_ERROR : MORPHE_STATUS_OK;
    build_resp_header(hdr, MORPHE_OP_FIR, dtype, status, n_out);

    if (dtype == MORPHE_DTYPE_INT32) {
        for (uint32_t i = 0; i < n_out; i++) i32_to_be(tx_buf + i * 4, y_buf[i]);
    } else {
        for (uint32_t i = 0; i < n_out; i++) f32_to_be(tx_buf + i * 4, (float) y_buf[i]);
    }

    if (send_all(sock, hdr, sizeof hdr) < 0) return -1;
    if (send_all(sock, tx_buf, (size_t) n_out * 4) < 0) return -1;
    
    LOG("  -> FIR OK: n_out=%u", n_out);
    return 0;
}

static int handle_fft(int sock, uint16_t dtype, uint32_t n_x) {
    LOG("FFT request: dtype=%u, n_x=%u", dtype, n_x);

    if (dtype != MORPHE_DTYPE_INT32) return send_error(sock, MORPHE_OP_FFT, MORPHE_STATUS_BAD_DTYPE, "FFT: use int32 (Q15.8)");
    if (n_x != MORPHE_FFT_N) return send_error(sock, MORPHE_OP_FFT, MORPHE_STATUS_BAD_SIZE, "FFT: N invalido");

    struct timespec t_start, t_after_recv, t_after_decode, t_after_fpga, t_after_pack, t_end;
    clock_gettime(CLOCK_MONOTONIC, &t_start);

    size_t payload_bytes = (size_t) n_x * 4;
    static uint8_t rx_buf[RX_BUF_MAX];
    if (recv_exact(sock, rx_buf, payload_bytes) < 0) return -1;
    clock_gettime(CLOCK_MONOTONIC, &t_after_recv);

    static int32_t xn_re_buf[MORPHE_FFT_N];
    decode_samples_to_q1508(rx_buf, n_x, xn_re_buf);
    clock_gettime(CLOCK_MONOTONIC, &t_after_decode);

    for (uint32_t i = 0; i < n_x; i++) {
        g_fft_xn_re[i]   = xn_re_buf[i];
        g_fft_xn_imag[i] = 0;
    }

    *g_pio_fft_inverse = 0;
    *g_pio_fft_start = 0;
    usleep(1);
    *g_pio_fft_start = 1;

    if (wait_done(g_pio_fft_done, FPGA_DONE_TIMEOUT_MS) < 0) {
        *g_pio_fft_start = 0;
        return send_error(sock, MORPHE_OP_FFT, MORPHE_STATUS_FPGA_TIMEOUT, "FFT: timeout");
    }
    *g_pio_fft_start = 0;
    clock_gettime(CLOCK_MONOTONIC, &t_after_fpga);

    uint32_t exp_raw = (*g_pio_fft_bfp_exp) & 0x3F;
    int32_t  bfp_exp = (exp_raw & 0x20) ? (int32_t)(exp_raw | 0xFFFFFFC0U) : (int32_t) exp_raw;
    float bfp_scale   = ldexpf(1.0f, -bfp_exp); /* y_real = y_raw * 2^(-exp) */
    float total_scale = bfp_scale / (float) MORPHE_Q1508_SCALE;

    static uint8_t tx_buf[TX_BUF_MAX];
    uint8_t hdr[MORPHE_HEADER_SIZE];
    build_resp_header(hdr, MORPHE_OP_FFT, MORPHE_DTYPE_FLOAT32, MORPHE_STATUS_OK, n_x);

    /* Copiando yn_re e yn_im localmente para passar pro debug bundle */
    static int32_t y_re_raw[MORPHE_FFT_N];
    static int32_t y_im_raw[MORPHE_FFT_N];

    for (uint32_t k = 0; k < n_x; k++) {
        y_re_raw[k] = g_fft_yn_re[k];
        y_im_raw[k] = g_fft_yn_imag[k];
        float re_f = (float) y_re_raw[k] * total_scale;
        float im_f = (float) y_im_raw[k] * total_scale;
        f32_to_be(tx_buf + k * 8 + 0, re_f);
        f32_to_be(tx_buf + k * 8 + 4, im_f);
    }
    clock_gettime(CLOCK_MONOTONIC, &t_after_pack);
    
    /* Salva bundle de debug (x_im é NULL pois a FFT recebe apenas entrada real) */
    save_debug_bundle_fft(n_x, xn_re_buf, NULL, y_re_raw, y_im_raw,
                          exp_raw, bfp_exp, total_scale);

    if (send_all(sock, hdr, sizeof hdr) < 0) return -1;
    if (send_all(sock, tx_buf, (size_t) n_x * 8) < 0) return -1;
    clock_gettime(CLOCK_MONOTONIC, &t_end);

    return 0;
}

static int handle_ping(int sock) {
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    long uptime_s = (long)(now.tv_sec - g_start_time.tv_sec);

    char body[512];
    int body_len = snprintf(body, sizeof body,
        "service=morphe\nversion=%u\nhostname=%s\nfft_n=%d\nfft_data_bits=%d\n"
        "fft_frac_bits=%d\nconv_n_max=%d\nconv_y_max=%d\nuptime_s=%ld\n",
        MORPHE_VERSION, g_hostname, MORPHE_FFT_N, MORPHE_FFT_DATA_BITS, 
        MORPHE_FFT_FRAC_BITS, MORPHE_CONV_N_MAX, MORPHE_CONV_Y_MAX, uptime_s);

    uint8_t hdr[MORPHE_HEADER_SIZE];
    build_resp_header(hdr, MORPHE_OP_PING, MORPHE_DTYPE_FLOAT32, MORPHE_STATUS_OK, (uint32_t) body_len);

    if (send_all(sock, hdr, sizeof hdr) < 0) return -1;
    if (send_all(sock, body, (size_t) body_len) < 0) return -1;
    return 0;
}

static void serve_connection(int sock) {
    uint8_t hdr[MORPHE_HEADER_SIZE];
    if (recv_exact(sock, hdr, sizeof hdr) < 0) return;

    uint32_t magic  = u32_from_be(hdr + 0);
    uint16_t ver, opcode, dtype, flags;
    memcpy(&ver,    hdr + 4,  2); ver    = ntohs(ver);
    memcpy(&opcode, hdr + 6,  2); opcode = ntohs(opcode);
    memcpy(&dtype,  hdr + 8,  2); dtype  = ntohs(dtype);
    memcpy(&flags,  hdr + 10, 2); flags  = ntohs(flags);
    uint32_t n_x = u32_from_be(hdr + 12);
    uint32_t n_h = u32_from_be(hdr + 16);
    (void) flags;

    if (magic != MORPHE_MAGIC_REQ) {
        send_error(sock, opcode, MORPHE_STATUS_BAD_MAGIC, "magic invalido");
        return;
    }
    if (ver != MORPHE_VERSION) {
        send_error(sock, opcode, MORPHE_STATUS_BAD_VERSION, "versao de protocolo nao suportada");
        return;
    }

    switch (opcode) {
        case MORPHE_OP_CONV: handle_conv(sock, dtype, n_x, n_h); break;
        case MORPHE_OP_FFT:  handle_fft(sock, dtype, n_x); break;
        case MORPHE_OP_FIR:  handle_fir(sock, dtype, n_x, n_h); break;
        case MORPHE_OP_PING: handle_ping(sock); break;
        default:
            send_error(sock, opcode, MORPHE_STATUS_BAD_OPCODE, "opcode desconhecido");
            break;
    }
}

int main(int argc, char **argv) {
    int port = MORPHE_DEFAULT_PORT;
    if (argc >= 2) port = atoi(argv[1]);

    clock_gettime(CLOCK_MONOTONIC, &g_start_time);
    if (gethostname(g_hostname, sizeof g_hostname) != 0) snprintf(g_hostname, sizeof g_hostname, "morphe-server");
    
    if (fpga_init() < 0) return 1;

    int srv = socket(AF_INET, SOCK_STREAM, 0);
    int one = 1;
    setsockopt(srv, SOL_SOCKET, SO_REUSEADDR, &one, sizeof one);

    struct sockaddr_in addr;
    memset(&addr, 0, sizeof addr);
    addr.sin_family      = AF_INET;
    addr.sin_addr.s_addr = htonl(INADDR_ANY);
    addr.sin_port        = htons((uint16_t) port);

    if (bind(srv, (struct sockaddr *)&addr, sizeof addr) < 0) return 1;
    if (listen(srv, 4) < 0) return 1;

    LOG("servidor ouvindo na porta %d", port);

    for (;;) {
        struct sockaddr_in peer;
        socklen_t plen = sizeof peer;
        int cli = accept(srv, (struct sockaddr *)&peer, &plen);
        if (cli < 0) continue;
        setsockopt(cli, IPPROTO_TCP, TCP_NODELAY, &one, sizeof one);
        serve_connection(cli);
        close(cli);
    }
    return 0;
}

