/*
 * morphe_server.c — servidor TCP no HPS da DE1-SoC.
 *
 * Recebe requests do host (Python) via protocolo Morphe, executa a operação
 * na FPGA (captura do ADC ou FFT) acessando SRAMs/PIOs mapeados em /dev/mem, e
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

#include <dirent.h>

#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <sys/types.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <arpa/inet.h>
#include <signal.h>
#include <pthread.h>
#include <ifaddrs.h>
#include <net/if.h>

#include "morphe_protocol.h"
#include "hps_0.h"
#include "address_map_arm.h"

#define ENABLE_DEBUG_FILES 1

/* Quantos bundles .mrph de depuracao manter por tipo de operacao. Antes nao
 * havia limite: cada operacao gravava um arquivo e nenhum era apagado, o que
 * enche o cartao SD de uma placa de laboratorio em silencio -- e cartao cheio
 * nao falha na hora, falha na proxima gravacao, longe da causa. Ajustavel em
 * tempo de execucao pela variavel de ambiente MORPHE_DUMP_MAX; 0 desliga. */
#define MORPHE_DUMP_MAX_PADRAO 100

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

/* O ADC so entra no servidor quando o hps_0.h foi GERADO de um .sopcinfo que o
 * tem (a RAM adc_buf e os cinco PIOs) e traz o timestamp do sysid. Nunca
 * escrever esses simbolos a mao: um cabecalho que descreve hardware que nao
 * esta na FPGA leva o servidor a tocar endereco sem escravo, e isso trava o
 * barramento do HPS (ver fpga_init). Sem eles, OP_ADC e recusado sem tocar
 * na FPGA. */
#if defined(ADC_BUF_BASE) && defined(ADC_START_BASE) && defined(ADC_DONE_BASE) && \
    defined(ADC_CONFIG_BASE) && defined(ADC_DIVISOR_BASE) && \
    defined(ADC_NAMOSTRAS_BASE) && defined(ADC_CONTADOR_BASE) && \
    defined(SYSID_QSYS_BASE) && defined(SYSID_QSYS_TIMESTAMP)
#define MORPHE_TEM_ADC 1
#define _MORPHE_END_ADC _MORPHE_END(ADC_BUF_BASE, ADC_BUF_SPAN)
#else
#define MORPHE_TEM_ADC 0
#define _MORPHE_END_ADC 0
#endif

#define MORPHE_ONCHIP_MMAP_SPAN \
    _MORPHE_ROUND_UP(_MORPHE_MAX2(_MORPHE_END_FFT, _MORPHE_END_ADC), _MORPHE_PAGE_SIZE)

_Static_assert(FFT_XN_RE_SPAN   >= MORPHE_FFT_N * (int)sizeof(int32_t), "Erro");
_Static_assert(FFT_XN_IMAG_SPAN >= MORPHE_FFT_N * (int)sizeof(int32_t), "Erro");
_Static_assert(FFT_YN_RE_SPAN   >= MORPHE_FFT_N * (int)sizeof(int32_t), "Erro");
_Static_assert(FFT_YN_IMAG_SPAN >= MORPHE_FFT_N * (int)sizeof(int32_t), "Erro");
#if MORPHE_TEM_ADC
_Static_assert(ADC_BUF_SPAN     >= MORPHE_ADC_N_MAX * (int)sizeof(int32_t), "Erro");
#endif
_Static_assert(MORPHE_ONCHIP_MMAP_SPAN <= FPGA_ONCHIP_SPAN + 1, "Erro");

#define FPGA_DONE_TIMEOUT_MS 5000
#define RX_BUF_MAX 16384
#define TX_BUF_MAX 32768

/* A saida complexa da FFT (2 int32 por bin) e o maior payload do servidor:
 * 8 KiB para N=1024. */
_Static_assert(MORPHE_FFT_N * 4 <= RX_BUF_MAX,
               "RX_BUF_MAX nao comporta a entrada da FFT");
_Static_assert(MORPHE_FFT_N * 8 <= TX_BUF_MAX,
               "TX_BUF_MAX nao comporta a saida complexa da FFT");

/* =======================================================================
 * Globais — ponteiros mapeados e fd de /dev/mem
 * ======================================================================= */
static int    g_fd_mem    = -1;

/* Marca de "FPGA preparada". Quem a cria e o morphe-up.sh, por SSH, depois
 * que o quartus_pgm confirmou a programacao do bitstream do Morphe. Fica em
 * /var/run (tmpfs): some sozinha no reboot -- que e exatamente quando o
 * U-Boot devolve a FPGA ao soc_system.rbf de fabrica. */
#define MORPHE_MARCA_FPGA "/var/run/morphe-fpga-preparada"

/* Assinatura do bitstream. Desde 22/10/2026 o ghrd_top liga a constante "MRPH"
 * no h2f_gp_in do HPS, que aparece no registrador GPI do FPGA manager. O
 * registrador e do HPS, nao da ponte: le-lo e seguro com qualquer bitstream,
 * inclusive o de fabrica e com a FPGA sem configuracao. Assim a placa sabe
 * que foi programada mesmo quando quem programou nao foi o morphe-up.sh (o
 * aplicativo, ao abrir) e nao ha marca. Um bitstream de antes disso nao tem a
 * assinatura e continua dependendo da marca. */
#define FPGAMGR_BASE       0xFF706000U
#define FPGAMGR_GPI        0x14U
#define MORPHE_ASSINATURA  0x4D525048U   /* "MRPH" */
static volatile uint32_t *g_fpgamgr = NULL;
static int    g_pios_zerados = 0;
static void  *g_fpga_virt = NULL;   
static void  *g_lw_virt   = NULL;   

static int32_t  *g_fft_xn_re   = NULL;
static int32_t  *g_fft_xn_imag = NULL;
static int32_t  *g_fft_yn_re   = NULL;
static int32_t  *g_fft_yn_imag = NULL;

#if MORPHE_TEM_ADC
static volatile uint32_t *g_adc_buf = NULL;   /* escrito pelo FPGA durante a captura */
static volatile uint32_t *g_sysid   = NULL;   /* [0] = id, [1] = timestamp do bitstream */
#endif

static volatile uint32_t *g_pio_fft_start    = NULL;
static volatile uint32_t *g_pio_fft_inverse  = NULL;
static volatile uint32_t *g_pio_fft_done     = NULL;
static volatile uint32_t *g_pio_fft_bfp_exp  = NULL;

#if MORPHE_TEM_ADC
static volatile uint32_t *g_pio_adc_start     = NULL;
static volatile uint32_t *g_pio_adc_done      = NULL;
static volatile uint32_t *g_pio_adc_config    = NULL;
static volatile uint32_t *g_pio_adc_divisor   = NULL;
static volatile uint32_t *g_pio_adc_namostras = NULL;
static volatile uint32_t *g_pio_adc_contador  = NULL;
#endif

static struct timespec  g_start_time;
static char             g_hostname[128] = "morphe-server";

/* Diagnostico: forca o bit `inverse` do IP da FFT no caminho do OP_FFT.
 *
 * Serve para responder, sem tocar no protocolo, se o bit esta vivo no
 * bitstream que esta na placa. Com MORPHE_FFT_INVERSE=1 no ambiente, uma
 * FFT comum de um sinal REAL passa a calcular a IDFT desse sinal, que
 * para entrada real e o conjugado da DFT (a menos da escala). Se a parte
 * imaginaria trocar de sinal em bloco, o bit funciona.
 *
 * Vale 0 na operacao normal. */
static int g_fft_force_inverse = 0;

#define LOG(fmt, ...) do { \
    fprintf(stderr, "[morphe] " fmt "\n", ##__VA_ARGS__); \
} while (0)

/* =======================================================================
 * Estado da placa, para a porta de estado (UDP, porta TCP + 1)
 *
 * O laco principal atende uma conexao por vez, entao uma placa ocupada nao
 * responde nem ao OP_PING ate terminar -- e o cliente nao distinguia "placa
 * ocupada" de "placa fora do ar". Uma thread a parte responde por UDP, NA
 * HORA, o que a placa esta fazendo: livre ou ocupada, qual operacao, ha
 * quanto tempo, e quantos computadores a usaram no ultimo minuto. O cliente
 * usa isso para escolher a placa e para explicar uma espera.
 *
 * A thread NAO toca a FPGA (nem le PIO): so estas variaveis e o stat() da
 * marca. Nao ha como ela travar o barramento do HPS.
 * ======================================================================= */
#define MORPHE_ESTADO_RECENTES     32     /* computadores distintos lembrados */
#define MORPHE_ESTADO_JANELA_S     60     /* "recentes" = ultimo minuto */

static pthread_mutex_t g_est_mtx = PTHREAD_MUTEX_INITIALIZER;
static const char     *g_est_op = NULL;            /* NULL = livre */
static struct timespec g_est_desde;                /* inicio da operacao atual */
static char            g_est_cliente[INET_ADDRSTRLEN] = "";
static unsigned long   g_est_atendidas = 0;        /* operacoes (sem PING) */
static struct { uint32_t ip; time_t quando; } g_est_recentes[MORPHE_ESTADO_RECENTES];

static const char *nome_op(uint16_t op) {
    switch (op) {
        case MORPHE_OP_FFT:  return "fft";
        case MORPHE_OP_ADC:  return "adc";
        case MORPHE_OP_ADC_CONTINUO: return "adc_continuo";
        default:             return "desconhecida";
    }
}

/* Chamado pelo laco principal antes de atender uma operacao (nao PING). */
static void estado_inicio(uint16_t op, const struct sockaddr_in *peer) {
    struct timespec agora;
    clock_gettime(CLOCK_MONOTONIC, &agora);
    pthread_mutex_lock(&g_est_mtx);
    g_est_op = nome_op(op);
    g_est_desde = agora;
    inet_ntop(AF_INET, &peer->sin_addr, g_est_cliente, sizeof g_est_cliente);
    g_est_atendidas++;
    /* o mesmo computador atualiza a propria entrada; um novo ocupa a mais velha */
    uint32_t ip = peer->sin_addr.s_addr;
    int alvo = 0;
    for (int i = 0; i < MORPHE_ESTADO_RECENTES; i++) {
        if (g_est_recentes[i].ip == ip) { alvo = i; break; }
        if (g_est_recentes[i].quando < g_est_recentes[alvo].quando) alvo = i;
    }
    g_est_recentes[alvo].ip = ip;
    g_est_recentes[alvo].quando = agora.tv_sec;
    pthread_mutex_unlock(&g_est_mtx);
}

static void estado_fim(void) {
    pthread_mutex_lock(&g_est_mtx);
    g_est_op = NULL;
    pthread_mutex_unlock(&g_est_mtx);
}

static int fpga_tem_morphe(void);

static int estado_texto(char *buf, size_t tam, int porta_tcp) {
    struct timespec agora;
    clock_gettime(CLOCK_MONOTONIC, &agora);
    int preparada = fpga_tem_morphe();

    pthread_mutex_lock(&g_est_mtx);
    int recentes = 0;
    for (int i = 0; i < MORPHE_ESTADO_RECENTES; i++)
        if (g_est_recentes[i].ip != 0
            && agora.tv_sec - g_est_recentes[i].quando <= MORPHE_ESTADO_JANELA_S)
            recentes++;
    long ha_ms = g_est_op
        ? (agora.tv_sec - g_est_desde.tv_sec) * 1000L
          + (agora.tv_nsec - g_est_desde.tv_nsec) / 1000000L
        : 0;
    int n = snprintf(buf, tam,
        "service=morphe-status\nversion=1\nhostname=%s\nporta_tcp=%d\n"
        "estado=%s\noperacao=%s\nha_ms=%ld\ncliente=%s\n"
        "clientes_recentes=%d\njanela_s=%d\natendidas=%lu\n"
        "uptime_s=%ld\nfpga_preparada=%d\n",
        g_hostname, porta_tcp,
        g_est_op ? "ocupada" : "livre", g_est_op ? g_est_op : "",
        ha_ms, g_est_op ? g_est_cliente : "",
        recentes, MORPHE_ESTADO_JANELA_S, g_est_atendidas,
        (long) (agora.tv_sec - g_start_time.tv_sec), preparada);
    pthread_mutex_unlock(&g_est_mtx);
    return n;
}

/* A thread da porta de estado. Responde a qualquer datagrama que comece com
 * "MRPS"; ignora o resto. Se a porta nao abrir, o servidor segue sem ela --
 * o cliente cai no metodo antigo (tempo do OP_PING). */
static void *thread_estado(void *arg) {
    int porta_tcp = *(int *) arg;
    int s = socket(AF_INET, SOCK_DGRAM, 0);
    if (s < 0) { LOG("porta de estado: socket falhou (%s)", strerror(errno)); return NULL; }
    struct sockaddr_in a;
    memset(&a, 0, sizeof a);
    a.sin_family = AF_INET;
    a.sin_addr.s_addr = htonl(INADDR_ANY);
    a.sin_port = htons((uint16_t) (porta_tcp + 1));
    if (bind(s, (struct sockaddr *) &a, sizeof a) < 0) {
        LOG("porta de estado: bind na UDP %d falhou (%s) -- seguindo sem ela",
            porta_tcp + 1, strerror(errno));
        close(s);
        return NULL;
    }
    LOG("porta de estado: UDP %d", porta_tcp + 1);
    for (;;) {
        char pedido[64], resp[512];
        struct sockaddr_in de;
        socklen_t lde = sizeof de;
        ssize_t r = recvfrom(s, pedido, sizeof pedido, 0, (struct sockaddr *) &de, &lde);
        if (r < 4 || memcmp(pedido, "MRPS", 4) != 0) continue;
        int n = estado_texto(resp, sizeof resp, porta_tcp);
        if (n > 0) sendto(s, resp, (size_t) n, 0, (struct sockaddr *) &de, lde);
    }
    return NULL;
}

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

    /* Sem esta pagina o servidor segue so com a marca, como antes. */
    void *mgr_pag = mmap(NULL, _MORPHE_PAGE_SIZE, PROT_READ, MAP_SHARED, g_fd_mem,
                         FPGAMGR_BASE);
    if (mgr_pag == MAP_FAILED)
        LOG("FPGA manager nao mapeado (%s): so a marca indica FPGA preparada", strerror(errno));
    else
        g_fpgamgr = (volatile uint32_t *) mgr_pag;

    g_fft_xn_re   = (int32_t *)((char *)g_fpga_virt + FFT_XN_RE_BASE);
    g_fft_xn_imag = (int32_t *)((char *)g_fpga_virt + FFT_XN_IMAG_BASE);
    g_fft_yn_re   = (int32_t *)((char *)g_fpga_virt + FFT_YN_RE_BASE);
    g_fft_yn_imag = (int32_t *)((char *)g_fpga_virt + FFT_YN_IMAG_BASE);

#if MORPHE_TEM_ADC
    g_adc_buf  = (volatile uint32_t *)((char *)g_fpga_virt + ADC_BUF_BASE);

    /* O sysid fica fora da janela LW mapeada acima (0x10000 > LW_BRIDGE_SPAN):
     * pagina propria. Mapear nao acessa nada; a leitura so acontece em
     * handle_adc, depois de fpga_preparada(). */
    void *sysid_pag = mmap(NULL, _MORPHE_PAGE_SIZE, PROT_READ, MAP_SHARED, g_fd_mem,
                           LW_BRIDGE_BASE + SYSID_QSYS_BASE);
    if (sysid_pag == MAP_FAILED) return -1;
    g_sysid = (volatile uint32_t *) sysid_pag;
#endif

    g_pio_fft_start   = (volatile uint32_t *)((char *)g_lw_virt + FFT_WRAPPER_START_BASE);
    g_pio_fft_inverse = (volatile uint32_t *)((char *)g_lw_virt + FFT_INVERSE_BASE);
    g_pio_fft_done    = (volatile uint32_t *)((char *)g_lw_virt + FFT_WRAPPER_DONE_BASE);
    g_pio_fft_bfp_exp = (volatile uint32_t *)((char *)g_lw_virt + FFT_BFP_EXPONENT_BASE);

#if MORPHE_TEM_ADC
    g_pio_adc_start     = (volatile uint32_t *)((char *)g_lw_virt + ADC_START_BASE);
    g_pio_adc_done      = (volatile uint32_t *)((char *)g_lw_virt + ADC_DONE_BASE);
    g_pio_adc_config    = (volatile uint32_t *)((char *)g_lw_virt + ADC_CONFIG_BASE);
    g_pio_adc_divisor   = (volatile uint32_t *)((char *)g_lw_virt + ADC_DIVISOR_BASE);
    g_pio_adc_namostras = (volatile uint32_t *)((char *)g_lw_virt + ADC_NAMOSTRAS_BASE);
    g_pio_adc_contador  = (volatile uint32_t *)((char *)g_lw_virt + ADC_CONTADOR_BASE);
#endif

    /* Nenhum acesso a FPGA aqui. Ate 21/09/2026 este ponto zerava os quatro
     * PIOs de start, e foi isso que derrubou a placa 2 no boot: com o
     * autostart, o servidor sobe 6 s depois do kernel, quando a FPGA ainda
     * carrega o soc_system.rbf de fabrica (o U-Boot o le do cartao), em que
     * esses enderecos nao existem. No Cyclone V, acesso a endereco sem escravo
     * na ponte HPS->FPGA trava o barramento L3 inteiro, sem timeout: a placa
     * some da rede e ate o login na serial congela. O zeramento ficou para
     * fpga_preparada(), que so o faz com a assinatura MRPH ou a marca do
     * morphe-up.sh. */
    LOG("FPGA mapeada. FFT_ONCHIP=%p (%u KiB)", g_fpga_virt, MORPHE_ONCHIP_MMAP_SPAN / 1024U);
    return 0;
}

static int fpga_tem_assinatura(void) {
    return g_fpgamgr && g_fpgamgr[FPGAMGR_GPI / 4] == MORPHE_ASSINATURA;
}

/* 1 se a FPGA esta com o bitstream do Morphe: assinatura no GPI ou marca do
 * morphe-up.sh. So le; serve tambem a thread da porta de estado. */
static int fpga_tem_morphe(void) {
    struct stat st;
    return fpga_tem_assinatura() || stat(MORPHE_MARCA_FPGA, &st) == 0;
}

/* Como fpga_tem_morphe(), e na passagem de "sem Morphe" para "com Morphe"
 * zera os PIOs de start -- o que fpga_init() fazia antes. A passagem pode
 * acontecer mais de uma vez com o servidor no ar: o aplicativo programa a
 * FPGA sem reiniciar o servidor. */
static int fpga_preparada(void) {
    if (!fpga_tem_morphe()) {
        g_pios_zerados = 0;
        return 0;
    }
    if (!g_pios_zerados) {
        *g_pio_fft_start  = 0;
#if MORPHE_TEM_ADC
        /* so se o bitstream carregado tem o ADC: o PIO pode nao existir */
        if (g_sysid[1] == SYSID_QSYS_TIMESTAMP) *g_pio_adc_start = 0;
#endif
        g_pios_zerados = 1;
        LOG("FPGA preparada (%s), PIOs de start zerados",
            fpga_tem_assinatura() ? "assinatura MRPH" : "marca " MORPHE_MARCA_FPGA);
    }
    return 1;
}

static int send_error(int sock, uint16_t opcode, uint16_t status, const char *msg);

static int recusar_sem_fpga(int sock, uint16_t op, const char *nome) {
    char msg[128];
    snprintf(msg, sizeof msg,
             "%s: FPGA nao preparada -- rode ./morphe-up.sh nesta placa", nome);
    LOG("  -> %s (sem assinatura MRPH e sem a marca %s)", msg, MORPHE_MARCA_FPGA);
    return send_error(sock, op, MORPHE_STATUS_FPGA_NAO_PREPARADA, msg);
}

static void fpga_shutdown(void) {
    if (g_fpga_virt) munmap(g_fpga_virt, MORPHE_ONCHIP_MMAP_SPAN);
    if (g_lw_virt)   munmap(g_lw_virt,   LW_BRIDGE_SPAN);
    if (g_fpgamgr)   munmap((void *) g_fpgamgr, _MORPHE_PAGE_SIZE);
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

/* Le e descarta o que o cliente ja enviou e o servidor nao vai consumir.
 *
 * Fechar um socket com dados nao lidos no buffer de recepcao faz o kernel
 * mandar RST em vez de FIN. O RST descarta o que ainda estava na fila de
 * saida -- inclusive a resposta de erro recem-enviada -- e o cliente ve
 * "Connection reset by peer" no lugar da mensagem. Era exatamente o que
 * acontecia com um pedido de FFT de tamanho errado: o servidor recusava
 * corretamente, com BAD_SIZE e tudo, e o cliente nunca chegava a ler a
 * recusa; parecia queda do servidor.
 *
 * O teto evita ficar refem de um cliente que continue despejando dados. */
static void drain_pending(int sock) {
    struct timeval espera = { .tv_sec = 0, .tv_usec = 200000 };
    setsockopt(sock, SOL_SOCKET, SO_RCVTIMEO, &espera, sizeof espera);

    uint8_t lixo[4096];
    size_t total = 0;
    for (;;) {
        ssize_t r = recv(sock, lixo, sizeof lixo, 0);
        if (r <= 0) break;
        total += (size_t) r;
        if (total > (size_t) RX_BUF_MAX) break;
    }

    struct timeval sem_limite = { .tv_sec = 0, .tv_usec = 0 };
    setsockopt(sock, SOL_SOCKET, SO_RCVTIMEO, &sem_limite, sizeof sem_limite);
}

static int send_error(int sock, uint16_t opcode, uint16_t status, const char *msg) {
    uint8_t hdr[MORPHE_HEADER_SIZE];
    size_t msg_len = strlen(msg);
    build_resp_header(hdr, opcode, MORPHE_DTYPE_FLOAT32, status, (uint32_t) msg_len);
    if (send_all(sock, hdr, sizeof hdr) < 0) return -1;
    if (msg_len > 0 && send_all(sock, msg, msg_len) < 0) return -1;
    LOG("  -> erro enviado: status=%u msg=\"%s\"", status, msg);
    drain_pending(sock);
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

static void decode_samples_to_q1508(const uint8_t *buf, uint32_t n, int32_t *out) {
    for (uint32_t i = 0; i < n; i++) out[i] = saturate_q1508(i32_from_be(buf + i * 4));
}


/* =======================================================================
 * Utilities: File Dumpers (.mrph bundles)
 * ======================================================================= */

/* Quantos bundles manter por prefixo. Lido de MORPHE_DUMP_MAX no main(). */
static int g_dump_max = MORPHE_DUMP_MAX_PADRAO;

/* Apaga os bundles mais antigos daquele prefixo, deixando espaco para o que
 * esta prestes a ser gravado. Os nomes carregam %Y%m%d_%H%M%S, entao ordem
 * alfabetica e ordem cronologica e basta apagar os primeiros da lista. */
static void rotate_dumps(const char *prefix, int manter) {
    if (manter <= 0) return;

    struct dirent **lista = NULL;
    int n = scandir(".", &lista, NULL, alphasort);
    if (n < 0) return;

    size_t plen = strlen(prefix);
    #define CASA(nome) ( strlen(nome) > plen + 5 \
                      && strncmp((nome), prefix, plen) == 0 \
                      && (nome)[plen] == '_' \
                      && strcmp((nome) + strlen(nome) - 5, ".mrph") == 0 )

    int casados = 0;
    for (int i = 0; i < n; i++)
        if (CASA(lista[i]->d_name)) casados++;

    int excedente = casados - (manter - 1);   /* -1 abre espaco para o novo */
    for (int i = 0; i < n && excedente > 0; i++) {
        if (CASA(lista[i]->d_name) && unlink(lista[i]->d_name) == 0) excedente--;
    }
    #undef CASA

    for (int i = 0; i < n; i++) free(lista[i]);
    free(lista);
}

static void save_debug_bundle_fft(const char *prefix, uint32_t n_x,
                                  const int32_t *x_re_raw, const int32_t *x_im_raw,
                                  const int32_t *y_re_raw, const int32_t *y_im_raw,
                                  uint32_t exp_raw, int32_t bfp_exp,
                                  float total_scale) {
#if ENABLE_DEBUG_FILES
    if (g_dump_max <= 0) return;
    rotate_dumps(prefix, g_dump_max);

    time_t now = time(NULL);
    struct tm *t = localtime(&now);
    char filename[128];
    char pat[64];
    snprintf(pat, sizeof pat, "%s_%%Y%%m%%d_%%H%%M%%S.mrph", prefix);
    strftime(filename, sizeof(filename), pat, t);
    
    FILE *f = fopen(filename, "w");
    if (!f) {
        LOG("Erro ao criar arquivo de debug %s", filename);
        return;
    }
    
    char timestamp[64];
    strftime(timestamp, sizeof(timestamp), "%Y-%m-%d %H:%M:%S", t);
    
    fprintf(f, "# MORPHE BUNDLE FILE\n");
    fprintf(f, "# saved: %s\n", timestamp);
    fprintf(f, "# title: %s server debug dump\n", prefix);
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


/* Cronometra as tres fases de um request e imprime.
 *
 * O `fpga` e o numero que interessa: o item 13 do RESSALVAS usa o tempo de
 * resposta como indicador de saude do core -- um IP amarrado no tether do
 * OpenCore Plus, ou parado, aparece aqui antes de aparecer no resultado.
 * O `saida` inclui a escrita do bundle .mrph quando ENABLE_DEBUG_FILES
 * esta ligado, que domina o tempo e nao e culpa do hardware. */
static void log_tempos(const char *op, const struct timespec *t0,
                       const struct timespec *t_entrada,
                       const struct timespec *t_fpga,
                       const struct timespec *t_fim) {
    LOG("  -> %s: entrada=%ldus fpga=%ldus saida=%ldus total=%ldus",
        op,
        ts_diff_us(t0, t_entrada),
        ts_diff_us(t_entrada, t_fpga),
        ts_diff_us(t_fpga, t_fim),
        ts_diff_us(t0, t_fim));
}

/* ADC: captura n_x amostras do LTC2308 a fs = 50 MHz / n_h, no
 * adc_captura.v. Sem payload de entrada; a palavra de configuracao do
 * conversor (canal, entrada simples ou diferencial, uni ou bipolar) vem no
 * campo flags do cabecalho.
 *
 * O instante de cada amostra e fixado pelo hardware; o servidor so dispara e
 * espera. A espera cresce com a captura (a 1 kHz, 32768 amostras levam 33 s),
 * por isso o timeout sai da propria duracao e nao do FPGA_DONE_TIMEOUT_MS.
 *
 * A RAM guarda o codigo cru de 12 bits. Em modo bipolar ele e complemento de
 * dois e o sinal e estendido aqui, para o cliente receber o numero com sinal.
 *
 * Antes de tocar em qualquer PIO do ADC, confere o timestamp do sysid contra o
 * do hps_0.h. O sysid existe em todos os bitstreams do Morphe, no mesmo
 * endereco, entao ler e seguro; os PIOs do ADC so existem no bitstream novo.
 * Um servidor novo com o bitstream antigo (o morphe-up ainda nao rodou, ou o
 * .sof nao foi recompilado depois do Generate) recusa aqui em vez de travar
 * o barramento. */
#if !MORPHE_TEM_ADC
static int recusar_sem_adc(int sock, uint16_t op) {
    LOG("ADC request recusado: servidor compilado sem o ADC");
    return send_error(sock, op, MORPHE_STATUS_BAD_OPCODE,
                      "ADC: este servidor foi compilado sem o ADC (o hps_0.h nao tem "
                      "adc_buf: gere o soc_system e rode gen_hps_header.py)");
}
static int handle_adc(int sock, uint16_t dtype, uint32_t n, uint32_t divisor, uint16_t cfg) {
    (void) dtype; (void) n; (void) divisor; (void) cfg;
    return recusar_sem_adc(sock, MORPHE_OP_ADC);
}
static int handle_adc_continuo(int sock, uint16_t dtype, uint32_t n, uint32_t divisor, uint16_t cfg) {
    (void) dtype; (void) n; (void) divisor; (void) cfg;
    return recusar_sem_adc(sock, MORPHE_OP_ADC_CONTINUO);
}
#else
/* O que as duas operacoes do ADC conferem antes de tocar na FPGA. Devolve 1
 * se recusou (a resposta de erro ja foi enviada) e 0 se pode seguir. */
static int adc_recusa(int sock, uint16_t op, uint16_t dtype, uint32_t divisor, uint16_t cfg) {
    if (!fpga_preparada()) { recusar_sem_fpga(sock, op, "ADC"); return 1; }

    uint32_t ts = g_sysid[1];
    if (ts != SYSID_QSYS_TIMESTAMP) {
        char msg[192];
        snprintf(msg, sizeof msg,
                 "ADC: o bitstream na FPGA (sysid %u) nao e o deste servidor (%u) -- "
                 "rode ./morphe-up.sh com o .sof que tem o ADC", ts, SYSID_QSYS_TIMESTAMP);
        LOG("  -> %s", msg);
        send_error(sock, op, MORPHE_STATUS_FPGA_NAO_PREPARADA, msg);
        return 1;
    }
    if (dtype != MORPHE_DTYPE_INT32) {
        send_error(sock, op, MORPHE_STATUS_BAD_DTYPE,
                   "ADC: a resposta e sempre int32 (codigos do conversor)");
        return 1;
    }
    if (divisor < MORPHE_ADC_DIV_MIN || divisor > MORPHE_ADC_DIV_MAX) {
        char msg[128];
        snprintf(msg, sizeof msg, "ADC: divisor fora de [%d, %d] (fs de %d a %d Hz)",
                 MORPHE_ADC_DIV_MIN, MORPHE_ADC_DIV_MAX,
                 MORPHE_ADC_CLK_HZ / MORPHE_ADC_DIV_MAX, MORPHE_ADC_CLK_HZ / MORPHE_ADC_DIV_MIN);
        send_error(sock, op, MORPHE_STATUS_BAD_SIZE, msg);
        return 1;
    }
    if (cfg > 0x3FU || (cfg & MORPHE_ADC_CFG_SLP)) {
        send_error(sock, op, MORPHE_STATUS_BAD_SIZE,
                   "ADC: configuracao invalida (6 bits, SLP = 0)");
        return 1;
    }
    return 0;
}

/* Codigo cru de 12 bits -> inteiro com sinal no modo bipolar. */
static int32_t adc_codigo(uint32_t palavra, int bipolar) {
    int32_t v = (int32_t) (palavra & 0xFFFU);
    if (bipolar && v >= 2048) v -= 4096;
    return v;
}

static int handle_adc(int sock, uint16_t dtype, uint32_t n, uint32_t divisor, uint16_t cfg) {
    LOG("ADC request: n=%u, divisor=%u (fs=%.1f Hz), config=0x%02x",
        n, divisor, divisor ? (double) MORPHE_ADC_CLK_HZ / divisor : 0.0, cfg);

    if (adc_recusa(sock, MORPHE_OP_ADC, dtype, divisor, cfg)) return 0;
    if (n == 0 || n > MORPHE_ADC_N_MAX) {
        char msg[128];
        snprintf(msg, sizeof msg, "ADC: amostras fora de [1, %d] (para mais, use a "
                 "captura continua)", MORPHE_ADC_N_MAX);
        return send_error(sock, MORPHE_OP_ADC, MORPHE_STATUS_BAD_SIZE, msg);
    }

    struct timespec t0, t_entrada, t_fpga, t_fim;
    clock_gettime(CLOCK_MONOTONIC, &t0);

    *g_pio_adc_divisor   = divisor;
    *g_pio_adc_namostras = n;
    *g_pio_adc_config    = cfg;          /* bit 6 = 0: captura unica */
    clock_gettime(CLOCK_MONOTONIC, &t_entrada);

    *g_pio_adc_start = 0;
    usleep(1);
    *g_pio_adc_start = 1;

    /* n+1 quadros (o primeiro e descartado) mais folga de 2 s */
    long duracao_ms = (long) (((uint64_t)(n + 1) * divisor * 1000U) / MORPHE_ADC_CLK_HZ);
    if (wait_done(g_pio_adc_done, (int) duracao_ms + 2000) < 0) {
        *g_pio_adc_start = 0;
        return send_error(sock, MORPHE_OP_ADC, MORPHE_STATUS_FPGA_TIMEOUT, "ADC: timeout");
    }
    *g_pio_adc_start = 0;
    clock_gettime(CLOCK_MONOTONIC, &t_fpga);

    static uint8_t tx_buf[MORPHE_ADC_N_MAX * 4];
    const int bipolar = (cfg & MORPHE_ADC_CFG_UNI) == 0;
    for (uint32_t i = 0; i < n; i++)
        i32_to_be(tx_buf + i * 4, adc_codigo(g_adc_buf[i], bipolar));

    uint8_t hdr[MORPHE_HEADER_SIZE];
    build_resp_header(hdr, MORPHE_OP_ADC, MORPHE_DTYPE_INT32, MORPHE_STATUS_OK, n);
    u32_to_be(hdr + 16, divisor);   /* extra: o divisor usado, fs = 50 MHz / extra */

    if (send_all(sock, hdr, sizeof hdr) < 0) return -1;
    if (send_all(sock, tx_buf, (size_t) n * 4) < 0) return -1;
    clock_gettime(CLOCK_MONOTONIC, &t_fim);

    LOG("  -> ADC OK: %u amostras", n);
    log_tempos("ADC", &t0, &t_entrada, &t_fpga, &t_fim);
    return 0;
}

/* Captura continua: o hardware grava sem parar na RAM, como buffer circular,
 * e este laco copia as amostras novas e as manda em blocos enquanto a captura
 * segue. Nao ha buraco no tempo entre um bloco e outro: quem fixa o instante
 * de cada amostra e o contador de periodo do FPGA, que nao para.
 *
 * O limite passa a ser o servidor acompanhar. A RAM guarda 32768 amostras, ou
 * 164 ms a 200 kHz: se o laco atrasar mais que isso (rede lenta, cliente que
 * nao le), amostras sao sobrescritas antes de copiadas. Isso NUNCA vira buraco
 * silencioso: o contador e relido depois de cada copia, e se o escritor passou
 * do ponto a captura termina com o estado PERDEU. Tudo o que foi enviado antes
 * continua valido e continuo.
 *
 * Termina quando: chegou a n_x amostras (se n_x > 0); o cliente mandou um byte
 * (pedido de parada) ou fechou a conexao; perdeu amostras; ou o contador parou
 * de andar (timeout do hardware). O servidor atende uma conexao por vez, entao
 * a placa fica ocupada durante toda a captura. */
#define MORPHE_ADC_BLOCO_MAX 8192

static int handle_adc_continuo(int sock, uint16_t dtype, uint32_t n_total, uint32_t divisor, uint16_t cfg) {
    LOG("ADC continuo: n=%u%s, divisor=%u (fs=%.1f Hz), config=0x%02x",
        n_total, n_total ? "" : " (ate o cliente parar)", divisor,
        divisor ? (double) MORPHE_ADC_CLK_HZ / divisor : 0.0, cfg);

    if (adc_recusa(sock, MORPHE_OP_ADC_CONTINUO, dtype, divisor, cfg)) return 0;

    /* cliente que para de ler nao pode prender o servidor para sempre */
    struct timeval espera = { .tv_sec = 5, .tv_usec = 0 };
    setsockopt(sock, SOL_SOCKET, SO_SNDTIMEO, &espera, sizeof espera);

    uint8_t tx_buf_fim_erro[8];
    uint8_t hdr[MORPHE_HEADER_SIZE];
    build_resp_header(hdr, MORPHE_OP_ADC_CONTINUO, MORPHE_DTYPE_INT32, MORPHE_STATUS_OK, 0);
    u32_to_be(hdr + 16, divisor);
    if (send_all(sock, hdr, sizeof hdr) < 0) return -1;

    struct timespec t0, t_ultimo, agora;
    clock_gettime(CLOCK_MONOTONIC, &t0);
    t_ultimo = t0;

    *g_pio_adc_divisor   = divisor;
    *g_pio_adc_namostras = 0;
    *g_pio_adc_config    = cfg | MORPHE_ADC_CFG_CONTINUO;
    /* Em repouso o contador do hardware vale 0 (adc_captura.v, S_DONE). Um
     * periodo maximo de espera garante o repouso mesmo se uma captura acabou
     * de ser interrompida; com o contador em 0 antes do start, nenhuma leitura
     * depois dele pode ver a contagem da captura anterior. */
    *g_pio_adc_start = 0;
    usleep(1100);                                    /* > 1 periodo a 1 kHz */
    if (*g_pio_adc_contador != 0) {
        uint32_t z = 0;
        LOG("  -> contador do ADC nao zerou em repouso");
        u32_to_be(tx_buf_fim_erro, z);
        u32_to_be(tx_buf_fim_erro + 4, MORPHE_ADC_BLOCO_TIMEOUT);
        send_all(sock, tx_buf_fim_erro, 8);
        return 0;
    }
    *g_pio_adc_start = 1;

    const int bipolar = (cfg & MORPHE_ADC_CFG_UNI) == 0;
    const uint32_t n_buf = MORPHE_ADC_N_MAX;               /* potencia de 2 */
    /* sem amostra nova por dois periodos mais 1 s: o hardware parou */
    const long prazo_us = (long) (((uint64_t) divisor * 2U * 1000000U) / MORPHE_ADC_CLK_HZ) + 1000000L;
    /* espera quando nao ha nada novo: ~1/8 da RAM, entre 1 e 20 ms */
    long pausa_us = (long) (((uint64_t) n_buf / 8U * divisor * 1000000U) / MORPHE_ADC_CLK_HZ);
    if (pausa_us < 1000) pausa_us = 1000;
    if (pausa_us > 20000) pausa_us = 20000;

    static uint8_t tx_buf[8 + MORPHE_ADC_BLOCO_MAX * 4];
    uint32_t lidos = 0;          /* mesma aritmetica modular do contador de 32 bits */
    uint64_t enviados = 0;
    uint32_t estado = MORPHE_ADC_BLOCO_FIM;
    int cliente_foi = 0;

    for (;;) {
        char c;
        ssize_t r = recv(sock, &c, 1, MSG_DONTWAIT);
        if (r == 1) { LOG("  -> o cliente pediu para parar"); break; }
        if (r == 0 || (r < 0 && errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR)) {
            cliente_foi = 1; LOG("  -> o cliente fechou a conexao"); break;
        }

        if (n_total && enviados >= n_total) break;

        uint32_t cont = *g_pio_adc_contador;
        uint32_t disp = cont - lidos;
        if (disp > n_buf) { estado = MORPHE_ADC_BLOCO_PERDEU; break; }
        if (disp == 0) {
            clock_gettime(CLOCK_MONOTONIC, &agora);
            if (ts_diff_us(&t_ultimo, &agora) > prazo_us) { estado = MORPHE_ADC_BLOCO_TIMEOUT; break; }
            usleep((useconds_t) pausa_us);
            continue;
        }
        uint32_t k = disp < MORPHE_ADC_BLOCO_MAX ? disp : MORPHE_ADC_BLOCO_MAX;
        if (n_total && (uint64_t) k > n_total - enviados) k = (uint32_t) (n_total - enviados);

        for (uint32_t i = 0; i < k; i++)
            i32_to_be(tx_buf + 8 + i * 4, adc_codigo(g_adc_buf[(lidos + i) & (n_buf - 1)], bipolar));

        /* o escritor passou da primeira amostra copiada? entao ela pode ter
         * sido sobrescrita durante a copia: descarta o bloco e para */
        if (*g_pio_adc_contador - lidos > n_buf) { estado = MORPHE_ADC_BLOCO_PERDEU; break; }

        u32_to_be(tx_buf + 0, k);
        u32_to_be(tx_buf + 4, MORPHE_ADC_BLOCO_SEGUE);
        if (send_all(sock, tx_buf, 8 + (size_t) k * 4) < 0) {
            cliente_foi = 1; LOG("  -> envio falhou: cliente fora"); break;
        }
        lidos += k;
        enviados += k;
        clock_gettime(CLOCK_MONOTONIC, &t_ultimo);
    }

    /* O quadro em curso termina (no maximo um periodo) e o hardware volta ao
     * repouso. O `done` do modo continuo pisca um ciclo so, curto demais para
     * a leitura por polling: espera-se o periodo, com folga. */
    *g_pio_adc_start = 0;
    usleep((useconds_t) (((uint64_t) divisor * 1000000U) / MORPHE_ADC_CLK_HZ) + 200U);

    if (!cliente_foi) {
        u32_to_be(tx_buf + 0, 0);
        u32_to_be(tx_buf + 4, estado);
        send_all(sock, tx_buf, 8);
    }
    struct timeval sem_limite = { .tv_sec = 0, .tv_usec = 0 };
    setsockopt(sock, SOL_SOCKET, SO_SNDTIMEO, &sem_limite, sizeof sem_limite);

    clock_gettime(CLOCK_MONOTONIC, &agora);
    double seg = (double) ts_diff_us(&t0, &agora) / 1e6;
    static const char *nomes[] = { "segue", "fim", "PERDEU AMOSTRAS", "TIMEOUT DO HARDWARE" };
    LOG("  -> ADC continuo: %llu amostras em %.2f s, termino: %s",
        (unsigned long long) enviados, seg, estado < 4 ? nomes[estado] : "?");
    return 0;
}

#endif /* MORPHE_TEM_ADC */

/* Dispara o IP da FFT sobre o que ja esta nas SRAMs de entrada e recolhe
 * o resultado. Unico ponto do servidor que fala com o hardware da FFT.
 * O argumento `inverse` so serve ao diagnostico MORPHE_FFT_INVERSE.
 *
 * O wrapper trava o bit `inverse` na borda de subida do `start`
 * (fft_wrapper.v:133), entao a ordem aqui e obrigatoria: escrever o bit,
 * garantir start baixo, e so entao subir o start.
 *
 * Devolve 0 em sucesso e -1 em timeout. Os y_*_raw sao os inteiros como
 * saem da SRAM; total_scale ja combina o expoente BFP com o Q15.8. */
static int fft_run_block(uint32_t n, int inverse,
                         int32_t *y_re_raw, int32_t *y_im_raw,
                         uint32_t *exp_raw_out, int32_t *bfp_exp_out,
                         float *total_scale_out) {
    *g_pio_fft_inverse = inverse ? 1u : 0u;
    *g_pio_fft_start = 0;
    usleep(1);
    *g_pio_fft_start = 1;

    if (wait_done(g_pio_fft_done, FPGA_DONE_TIMEOUT_MS) < 0) {
        *g_pio_fft_start = 0;
        return -1;
    }
    *g_pio_fft_start = 0;

    uint32_t exp_raw = (*g_pio_fft_bfp_exp) & 0x3F;
    int32_t  bfp_exp = (exp_raw & 0x20) ? (int32_t)(exp_raw | 0xFFFFFFC0U) : (int32_t) exp_raw;
    float bfp_scale   = ldexpf(1.0f, -bfp_exp); /* y_real = y_raw * 2^(-exp) */

    for (uint32_t k = 0; k < n; k++) {
        y_re_raw[k] = g_fft_yn_re[k];
        y_im_raw[k] = g_fft_yn_imag[k];
    }

    *exp_raw_out     = exp_raw;
    *bfp_exp_out     = bfp_exp;
    *total_scale_out = bfp_scale / (float) MORPHE_Q1508_SCALE;
    return 0;
}

/* Empacota N bins complexos em float32 big-endian, re e im intercalados:
 * o formato de resposta da FFT. */
static void pack_complex_be(uint8_t *tx, uint32_t n,
                            const int32_t *re_raw, const int32_t *im_raw,
                            float scale) {
    for (uint32_t k = 0; k < n; k++) {
        f32_to_be(tx + k * 8 + 0, (float) re_raw[k] * scale);
        f32_to_be(tx + k * 8 + 4, (float) im_raw[k] * scale);
    }
}

static int handle_fft(int sock, uint16_t dtype, uint32_t n_x) {
    LOG("FFT request: dtype=%u, n_x=%u", dtype, n_x);

    if (!fpga_preparada()) return recusar_sem_fpga(sock, MORPHE_OP_FFT, "FFT");

    if (dtype != MORPHE_DTYPE_INT32) return send_error(sock, MORPHE_OP_FFT, MORPHE_STATUS_BAD_DTYPE, "FFT: use int32 (Q15.8)");
    if (n_x != MORPHE_FFT_N) return send_error(sock, MORPHE_OP_FFT, MORPHE_STATUS_BAD_SIZE, "FFT: N invalido");

    struct timespec t0, t_entrada, t_fpga, t_fim;
    clock_gettime(CLOCK_MONOTONIC, &t0);

    size_t payload_bytes = (size_t) n_x * 4;
    static uint8_t rx_buf[RX_BUF_MAX];
    if (recv_exact(sock, rx_buf, payload_bytes) < 0) return -1;

    static int32_t xn_re_buf[MORPHE_FFT_N];
    decode_samples_to_q1508(rx_buf, n_x, xn_re_buf);

    for (uint32_t i = 0; i < n_x; i++) {
        g_fft_xn_re[i]   = xn_re_buf[i];
        g_fft_xn_imag[i] = 0;
    }
    clock_gettime(CLOCK_MONOTONIC, &t_entrada);

    static int32_t y_re_raw[MORPHE_FFT_N];
    static int32_t y_im_raw[MORPHE_FFT_N];
    uint32_t exp_raw; int32_t bfp_exp; float total_scale;

    if (fft_run_block(n_x, g_fft_force_inverse, y_re_raw, y_im_raw,
                      &exp_raw, &bfp_exp, &total_scale) < 0) {
        return send_error(sock, MORPHE_OP_FFT, MORPHE_STATUS_FPGA_TIMEOUT, "FFT: timeout");
    }
    clock_gettime(CLOCK_MONOTONIC, &t_fpga);
    if (g_fft_force_inverse) LOG("  (rodou com inverse=1 -- diagnostico)");

    static uint8_t tx_buf[TX_BUF_MAX];
    uint8_t hdr[MORPHE_HEADER_SIZE];
    build_resp_header(hdr, MORPHE_OP_FFT, MORPHE_DTYPE_FLOAT32, MORPHE_STATUS_OK, n_x);
    pack_complex_be(tx_buf, n_x, y_re_raw, y_im_raw, total_scale);

    /* Salva bundle de debug (x_im é NULL pois a FFT recebe apenas entrada real) */
    save_debug_bundle_fft("fft", n_x, xn_re_buf, NULL, y_re_raw, y_im_raw,
                          exp_raw, bfp_exp, total_scale);

    if (send_all(sock, hdr, sizeof hdr) < 0) return -1;
    if (send_all(sock, tx_buf, (size_t) n_x * 8) < 0) return -1;
    clock_gettime(CLOCK_MONOTONIC, &t_fim);

    log_tempos("FFT", &t0, &t_entrada, &t_fpga, &t_fim);
    return 0;
}

static int handle_ping(int sock) {
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    long uptime_s = (long)(now.tv_sec - g_start_time.tv_sec);

    /* adc_n_max = 0 quando o ADC nao pode ser usado agora: servidor compilado
     * sem ele, FPGA ainda sem o bitstream do Morphe, ou bitstream sem o ADC
     * (sysid diferente do hps_0.h). Ler o sysid e seguro com a FPGA preparada. */
    int preparada = fpga_preparada();
    int adc_ok = 0;
#if MORPHE_TEM_ADC
    adc_ok = preparada && g_sysid[1] == SYSID_QSYS_TIMESTAMP;
#endif

    char body[512];
    int body_len = snprintf(body, sizeof body,
        "service=morphe\nversion=%u\nhostname=%s\nfft_n=%d\nfft_data_bits=%d\n"
        "fft_frac_bits=%d\nadc_n_max=%d\nadc_fs_max=%d\n"
        "adc_fs_min=%d\nuptime_s=%ld\nfpga_preparada=%d\n",
        MORPHE_VERSION, g_hostname, MORPHE_FFT_N, MORPHE_FFT_DATA_BITS,
        MORPHE_FFT_FRAC_BITS,
        adc_ok ? MORPHE_ADC_N_MAX : 0,
        MORPHE_ADC_CLK_HZ / MORPHE_ADC_DIV_MIN, MORPHE_ADC_CLK_HZ / MORPHE_ADC_DIV_MAX,
        uptime_s, preparada);

    uint8_t hdr[MORPHE_HEADER_SIZE];
    build_resp_header(hdr, MORPHE_OP_PING, MORPHE_DTYPE_FLOAT32, MORPHE_STATUS_OK, (uint32_t) body_len);

    if (send_all(sock, hdr, sizeof hdr) < 0) return -1;
    if (send_all(sock, body, (size_t) body_len) < 0) return -1;
    return 0;
}

static void serve_connection(int sock, const struct sockaddr_in *peer) {
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

    if (magic != MORPHE_MAGIC_REQ) {
        send_error(sock, opcode, MORPHE_STATUS_BAD_MAGIC, "magic invalido");
        return;
    }
    if (ver != MORPHE_VERSION) {
        send_error(sock, opcode, MORPHE_STATUS_BAD_VERSION, "versao de protocolo nao suportada");
        return;
    }

    /* O PING nao conta como uso: todo cliente sonda todas as placas ao abrir. */
    const int conta = opcode != MORPHE_OP_PING;
    if (conta) estado_inicio(opcode, peer);

    switch (opcode) {
        case MORPHE_OP_FFT:  handle_fft(sock, dtype, n_x); break;
        case MORPHE_OP_ADC:  handle_adc(sock, dtype, n_x, n_h, flags); break;
        case MORPHE_OP_ADC_CONTINUO: handle_adc_continuo(sock, dtype, n_x, n_h, flags); break;
        case MORPHE_OP_PING: handle_ping(sock); break;
        default:
            send_error(sock, opcode, MORPHE_STATUS_BAD_OPCODE, "opcode desconhecido");
            break;
    }
    if (conta) estado_fim();
}

int main(int argc, char **argv) {
    int port = MORPHE_DEFAULT_PORT;
    if (argc >= 2) port = atoi(argv[1]);

    /* Cliente que fecha a conexao no meio da resposta nao pode matar o
     * servidor: sem isto, o send() seguinte levanta SIGPIPE, cuja acao padrao
     * encerra o processo. Com SIG_IGN o send() so devolve EPIPE. E o jeito
     * normal de a captura continua terminar, e tambem o que acontece quando
     * um aluno fecha a janela durante uma operacao longa. */
    signal(SIGPIPE, SIG_IGN);

    clock_gettime(CLOCK_MONOTONIC, &g_start_time);
    if (gethostname(g_hostname, sizeof g_hostname) != 0) snprintf(g_hostname, sizeof g_hostname, "morphe-server");

    const char *env_dump = getenv("MORPHE_DUMP_MAX");
    if (env_dump && *env_dump) g_dump_max = atoi(env_dump);
    if (g_dump_max > 0)
        LOG("bundles de depuracao: ate %d por operacao, os mais antigos sao apagados",
            g_dump_max);
    else
        LOG("bundles de depuracao desligados (MORPHE_DUMP_MAX=%d)", g_dump_max);

    const char *env_inv = getenv("MORPHE_FFT_INVERSE");
    g_fft_force_inverse = (env_inv && atoi(env_inv) != 0) ? 1 : 0;
    if (g_fft_force_inverse) {
        LOG("DIAGNOSTICO: MORPHE_FFT_INVERSE=1 -- o OP_FFT vai rodar com o");
        LOG("             bit inverse LIGADO. Nao e a operacao normal.");
    }


    if (fpga_init() < 0) return 1;
    atexit(fpga_shutdown);   /* existia desde sempre e nunca era chamada */

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

    /* Porta de estado (UDP, porta + 1). Falhar aqui nao impede o servico. */
    static int porta_estado;
    porta_estado = port;
    pthread_t th_estado;
    if (pthread_create(&th_estado, NULL, thread_estado, &porta_estado) == 0)
        pthread_detach(th_estado);
    else
        LOG("porta de estado: a thread nao subiu -- seguindo sem ela");

    LOG("servidor ouvindo na porta %d", port);

    for (;;) {
        struct sockaddr_in peer;
        socklen_t plen = sizeof peer;
        int cli = accept(srv, (struct sockaddr *)&peer, &plen);
        if (cli < 0) continue;
        setsockopt(cli, IPPROTO_TCP, TCP_NODELAY, &one, sizeof one);
        serve_connection(cli, &peer);
        close(cli);
    }
    return 0;
}

