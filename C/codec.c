/*
 * codec.c -- configura o codec de audio WM8731 da DE1-SoC pelo HPS.
 *
 * O barramento I2C do codec passa por um multiplexador: com o pino
 * HPS_I2C_CONTROL (GPIO48 do HPS = bit 19 do GPIO1) em 1, quem fala com o
 * codec e o controlador I2C0 do HPS; em 0, a FPGA (manual da DE1-SoC, 3.6.5).
 * O ghrd_top.v ja liga o I2C0 e o GPIO48 aos pinos, entao isto funciona com o
 * bitstream que estiver na placa -- nao precisa recompilar.
 *
 * Caminho do I2C, nesta ordem:
 *   1. /dev/i2c-N do Linux, se existir (o N do controlador ffc04000 e achado
 *      no /sys; --bus N escolhe na mao);
 *   2. sem /dev/i2c-*, ou com --direto: o controlador I2C0 (DesignWare,
 *      0xFFC04000) programado direto pelos registradores, via /dev/mem.
 *
 * O WM8731 so aceita escrita: cada registrador tem 9 bits e cada escrita sao
 * 2 bytes, (reg << 1 | bit 8 do dado) e (bits 7..0 do dado), no endereco 0x1A.
 * "Detectar" = ver se o codec responde (ACK) a uma escrita inofensiva.
 *
 * Uso (como root, na placa):
 *   ./codec detecta              o codec responde no I2C?
 *   ./codec bypass               etapa 1: LINE-in -> LINE-out pelo caminho
 *                                analogico do chip (sem FPGA, sem relogio)
 *   ./codec digital              etapa 2: I2S, 16 bits, codec mestre, 256 fs;
 *                                com AUD_XCK = 12,5 MHz da FPGA, fs = 48 828 Hz
 *   ./codec desliga              reset: o codec volta a ficar mudo
 *   ./codec escreve <reg> <val>  um registrador qualquer (aceita 0x..)
 * Opcoes: --volume <dB>  saida de fone/linha, de -73 a +6 (padrao -10)
 *         --entrada mic  no modo digital, le o MIC-in (rosa) com +20 dB em vez
 *                        da LINE-in (azul); "--entrada linha" e o padrao
 *         --mux 0        diagnostico: deixa o I2C do codec com a FPGA
 *         --addr <a>     diagnostico: outro endereco (0x53 = acelerometro,
 *                        do lado do HPS, antes do multiplexador)
 *         --bus <N>      usa /dev/i2c-N
 *         --direto       ignora o /dev/i2c-* e programa o controlador
 *
 * Compilar na placa:  make codec   (ou gcc -std=gnu99 -O2 -o codec codec.c)
 */
#include <errno.h>
#include <fcntl.h>
#include <glob.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <unistd.h>
#include <linux/i2c-dev.h>

#define CODEC_ADDR      0x1A

#define GPIO1_BASE      0xFF709000u   /* GPIO29..57; GPIO48 = bit 19 */
#define GPIO_DR         0x00
#define GPIO_DDR        0x04
#define BIT_I2C_CONTROL (1u << 19)

#define RSTMGR_BASE     0xFFD05000u
#define RSTMGR_PERMODRST 0x14
#define RST_I2C0        (1u << 12)
#define RST_GPIO1       (1u << 26)

#define I2C0_BASE       0xFFC04000u   /* controlador DesignWare */
#define IC_CON          0x00
#define IC_TAR          0x04
#define IC_DATA_CMD     0x10
#define IC_SS_SCL_HCNT  0x14
#define IC_SS_SCL_LCNT  0x18
#define IC_RAW_INTR_STAT 0x34
#define IC_CLR_TX_ABRT  0x54
#define IC_ENABLE       0x6C
#define IC_STATUS       0x70
#define IC_TX_ABRT_SOURCE 0x80
#define IC_ENABLE_STATUS 0x9C

static int fd_mem = -1;
static int endereco = CODEC_ADDR;   /* --addr: so para diagnostico */

static volatile uint32_t *mapeia(uint32_t base)
{
    if (fd_mem < 0) {
        fd_mem = open("/dev/mem", O_RDWR | O_SYNC);
        if (fd_mem < 0) { perror("/dev/mem (rodar como root)"); exit(1); }
    }
    void *p = mmap(NULL, 0x1000, PROT_READ | PROT_WRITE, MAP_SHARED, fd_mem, base);
    if (p == MAP_FAILED) { perror("mmap"); exit(1); }
    return (volatile uint32_t *)p;
}

#define REG(b, off) (*(volatile uint32_t *)((volatile uint8_t *)(b) + (off)))

/* ---- multiplexador do I2C: HPS_I2C_CONTROL = 1 ---------------------------- */
static void mux_para_hps(int valor)
{
    volatile uint32_t *rst = mapeia(RSTMGR_BASE);
    if (REG(rst, RSTMGR_PERMODRST) & RST_GPIO1) {
        printf("GPIO1 estava em reset; soltando.\n");
        REG(rst, RSTMGR_PERMODRST) &= ~RST_GPIO1;
    }
    volatile uint32_t *g = mapeia(GPIO1_BASE);
    uint32_t antes = REG(g, GPIO_DR) & BIT_I2C_CONTROL;
    if (valor) REG(g, GPIO_DR) |= BIT_I2C_CONTROL;
    else       REG(g, GPIO_DR) &= ~BIT_I2C_CONTROL;
    REG(g, GPIO_DDR) |= BIT_I2C_CONTROL;
    printf("HPS_I2C_CONTROL (GPIO48): %d -> %d (%s)\n", antes ? 1 : 0, valor,
           valor ? "o HPS fica com o I2C do codec" : "I2C do codec com a FPGA");
}

/* ---- caminho 1: /dev/i2c-N ------------------------------------------------ */
static int fd_i2c = -1;

static int acha_bus_i2c0(void)
{
    /* o i2c-N cujo dispositivo e o controlador em ffc04000 */
    glob_t g;
    int achado = -1;
    if (glob("/sys/bus/i2c/devices/i2c-*", 0, NULL, &g) == 0) {
        for (size_t i = 0; i < g.gl_pathc && achado < 0; i++) {
            char real[PATH_MAX];
            if (realpath(g.gl_pathv[i], real) && strstr(real, "ffc04000"))
                achado = atoi(strrchr(g.gl_pathv[i], '-') + 1);
        }
        globfree(&g);
    }
    if (achado < 0 && access("/dev/i2c-0", F_OK) == 0)
        achado = 0;      /* sem /sys legivel: o I2C0 costuma ser o primeiro */
    return achado;
}

static int abre_dev_i2c(int bus)
{
    char nome[32];
    snprintf(nome, sizeof nome, "/dev/i2c-%d", bus);
    fd_i2c = open(nome, O_RDWR);
    if (fd_i2c < 0) { fprintf(stderr, "%s: %s\n", nome, strerror(errno)); return -1; }
    if (ioctl(fd_i2c, I2C_SLAVE, endereco) < 0 &&
        ioctl(fd_i2c, I2C_SLAVE_FORCE, endereco) < 0) {
        fprintf(stderr, "ioctl I2C_SLAVE 0x%02X: %s\n", endereco, strerror(errno));
        return -1;
    }
    printf("I2C: %s\n", nome);
    return 0;
}

/* ---- caminho 2: controlador DesignWare direto ----------------------------- */
static volatile uint32_t *i2c = NULL;

static int abre_direto(void)
{
    volatile uint32_t *rst = mapeia(RSTMGR_BASE);
    if (REG(rst, RSTMGR_PERMODRST) & RST_I2C0) {
        printf("I2C0 estava em reset; soltando.\n");
        REG(rst, RSTMGR_PERMODRST) &= ~RST_I2C0;
        usleep(1000);
    }
    i2c = mapeia(I2C0_BASE);
    /* uma execucao anterior pode ter deixado o controlador preso no meio de uma
       transferencia (SCL segurado em 0): ABORT antes de desabilitar */
    if (REG(i2c, IC_STATUS) & (1u << 5)) {
        REG(i2c, IC_ENABLE) = 3;
        usleep(10000);
    }
    REG(i2c, IC_ENABLE) = 0;
    for (int t = 0; (REG(i2c, IC_ENABLE_STATUS) & 1) && t < 100; t++) usleep(100);
    /* mestre, modo padrao (100 kHz), restart, escravo desligado */
    REG(i2c, IC_CON) = 0x63;
    REG(i2c, IC_TAR) = endereco;
    /* l4_sp_clk tipico de 100 MHz: 1000 + 1000 ciclos = 50 kHz. Mais lento que o
       necessario de proposito: funciona mesmo que o relogio seja outro. */
    REG(i2c, IC_SS_SCL_HCNT) = 1000;
    REG(i2c, IC_SS_SCL_LCNT) = 1000;
    REG(i2c, IC_ENABLE) = 1;
    printf("I2C: controlador I2C0 direto (0x%08X)\n", I2C0_BASE);
    return 0;
}

static int escreve_direto(uint8_t b0, uint8_t b1)
{
    (void)REG(i2c, IC_CLR_TX_ABRT);
    REG(i2c, IC_DATA_CMD) = b0;
    /* bit 9 = STOP: o I2C0 do Cyclone V tem IC_EMPTYFIFO_HOLD_MASTER_EN; sem
       esse bit, FIFO vazia NAO gera STOP -- o mestre segura o SCL em 0
       esperando mais dados (medido na placa 1 em 13/10: START sem STOP) */
    REG(i2c, IC_DATA_CMD) = b1 | (1u << 9);
    for (int t = 0; t < 2000; t++) {
        uint32_t st = REG(i2c, IC_STATUS);
        if (REG(i2c, IC_RAW_INTR_STAT) & (1u << 6)) {        /* TX_ABRT */
            uint32_t fonte = REG(i2c, IC_TX_ABRT_SOURCE);
            (void)REG(i2c, IC_CLR_TX_ABRT);
            fprintf(stderr, "  sem ACK (TX_ABRT_SOURCE = 0x%X)\n", fonte);
            return -1;
        }
        if ((st & (1u << 2)) && !(st & (1u << 5)))           /* TFE e !MST_ACTIVITY */
            return 0;
        usleep(50);
    }
    fprintf(stderr, "  tempo esgotado esperando o I2C (IC_STATUS = 0x%X, RAW_INTR = 0x%X)\n"
                    "  START sem STOP: SCL preso em 0 (FPGA_I2C_SCLK aterrado pelo bitstream?)\n",
            REG(i2c, IC_STATUS), REG(i2c, IC_RAW_INTR_STAT));
    REG(i2c, IC_ENABLE) = 3;           /* ABORT: solta o controlador */
    usleep(10000);
    return -1;
}

/* ---- escrita de um registrador do WM8731 ---------------------------------- */
static int escreve(int reg, int val)
{
    uint8_t b[2] = { (uint8_t)((reg << 1) | ((val >> 8) & 1)), (uint8_t)(val & 0xFF) };
    int r;
    if (fd_i2c >= 0) {
        r = (write(fd_i2c, b, 2) == 2) ? 0 : -1;
        if (r) fprintf(stderr, "  write: %s\n", strerror(errno));
    } else {
        r = escreve_direto(b[0], b[1]);
    }
    printf("  R%-2d <- 0x%03X  %s\n", reg, val & 0x1FF, r ? "FALHOU" : "ok");
    return r;
}

/* ---- sequencias ------------------------------------------------------------ */
static int hp_vol(int db)
{
    /* R2/R3: 0x79 = 0 dB, passos de 1 dB; 0x30 = -73 dB, 0x7F = +6 dB */
    if (db < -73) db = -73;
    if (db > 6)   db = 6;
    return 0x100 | (0x79 + db);        /* bit 8: vale para os dois canais */
}

static int seq_bypass(int db)
{
    int e = 0;
    e |= escreve(15, 0x000);           /* reset */
    e |= escreve(0, 0x117);            /* LINE-in 0 dB, sem mute, os dois canais */
    e |= escreve(2, hp_vol(db));       /* saida, os dois canais */
    e |= escreve(4, 0x00A);            /* BYPASS=1, MUTEMIC=1, INSEL=LINE, DACSEL=0 */
    e |= escreve(5, 0x008);            /* DAC mudo (nao entra no bypass) */
    e |= escreve(6, 0x06E);            /* ligados: LINE-in e saida; resto desligado */
    return e;
}

static int seq_digital(int db, int mic)
{
    int e = 0;
    e |= escreve(15, 0x000);           /* reset */
    e |= escreve(0, 0x117);            /* LINE-in 0 dB, os dois canais */
    e |= escreve(2, hp_vol(db));
    if (mic)
        e |= escreve(4, 0x015);        /* DACSEL=1, INSEL=MIC, MUTEMIC=0, MICBOOST=1 (+20 dB) */
    else
        e |= escreve(4, 0x012);        /* DACSEL=1, MUTEMIC=1, INSEL=LINE, sem bypass */
    e |= escreve(5, 0x000);            /* passa-altas do ADC ligado, DAC sem mute */
    /* R6: tudo ligado menos osc e CLKOUT (e MIC, se a entrada for a LINE-in);
       a saida (OUTPD, bit 4) liga por ultimo, para evitar estalo */
    int r6 = mic ? 0x060 : 0x062;
    e |= escreve(6, r6 | 0x010);
    e |= escreve(7, 0x042);            /* MS=1 (codec mestre), I2S, 16 bits */
    e |= escreve(8, 0x000);            /* modo normal, 256 fs, SR=0000 */
    e |= escreve(9, 0x001);            /* interface ativa */
    e |= escreve(6, r6);
    return e;
}

static void uso(void)
{
    fprintf(stderr,
        "uso: codec [--volume dB] [--entrada linha|mic] [--bus N] [--direto] [--mux 0|1] [--addr A] "
        "detecta | bypass | digital | desliga | escreve <reg> <val>\n");
    exit(2);
}

int main(int argc, char **argv)
{
    int db = -10, bus = -1, direto = 0, mux = 1, mic = 0, i = 1;
    for (; i < argc && strncmp(argv[i], "--", 2) == 0; i++) {
        if (!strcmp(argv[i], "--volume") && i + 1 < argc)   db = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--entrada") && i + 1 < argc) {
            i++;
            if (!strcmp(argv[i], "mic"))       mic = 1;
            else if (!strcmp(argv[i], "linha")) mic = 0;
            else uso();
        }
        else if (!strcmp(argv[i], "--bus") && i + 1 < argc) bus = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--direto"))              direto = 1;
        else if (!strcmp(argv[i], "--mux") && i + 1 < argc) mux = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--addr") && i + 1 < argc)
            endereco = (int)strtol(argv[++i], NULL, 0);
        else uso();
    }
    if (i >= argc) uso();
    const char *cmd = argv[i];

    mux_para_hps(mux);
    if (!direto) {
        if (bus < 0) bus = acha_bus_i2c0();
        if (bus >= 0 && abre_dev_i2c(bus) == 0) direto = 0;
        else {
            printf("sem /dev/i2c utilizavel; usando o controlador direto\n");
            direto = 1;
        }
    }
    if (direto) abre_direto();

    int e;
    if (!strcmp(cmd, "detecta")) {
        e = escreve(9, 0x000);         /* "interface inativa": inofensivo */
        printf(e ? "NADA respondeu no endereco 0x%02X.\n"
                 : "Respondeu no endereco 0x%02X.\n", endereco);
    } else if (!strcmp(cmd, "bypass")) {
        e = seq_bypass(db);
        if (!e) printf("Bypass ligado: o som da LINE-in deve sair na LINE-out, "
                       "volume %d dB. Sem FPGA no caminho.\n", db);
    } else if (!strcmp(cmd, "digital")) {
        e = seq_digital(db, mic);
        if (!e) printf("Modo digital: I2S 16 bits, codec mestre, entrada %s. Com o "
                       "bitstream do audio_i2s.v: SW9 baixa = entrada -> FPGA -> LINE-out; "
                       "SW9 alta = tom de 1017 Hz. Nivel da entrada em HEX0..HEX4.\n",
                       mic ? "MIC-in (rosa, +20 dB)" : "LINE-in (azul)");
    } else if (!strcmp(cmd, "desliga")) {
        e = escreve(15, 0x000);
    } else if (!strcmp(cmd, "escreve") && i + 2 < argc) {
        e = escreve((int)strtol(argv[i + 1], NULL, 0), (int)strtol(argv[i + 2], NULL, 0));
    } else {
        uso();
        e = 1;
    }
    return e ? 1 : 0;
}
