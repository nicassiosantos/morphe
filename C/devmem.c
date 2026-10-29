/* devmem.c -- le e escreve um endereco fisico, como o "devmem" do busybox.
 *
 * O Linux das placas do laboratorio nao tem busybox, entao nao tem devmem.
 * Este e o substituto, com a mesma sintaxe, usado no teste isolado do
 * roteiro do modulo (docs/roteiro-modulo, passo A6):
 *
 *   ./devmem 0xFF200150 32 0x00018000    escreve 32 bits
 *   ./devmem 0xFF200170                  le 32 bits e imprime em hex
 *
 * Compila na placa: make devmem (o morphe-up.sh --deploy ja faz).
 *
 * CUIDADO: ler ou escrever um endereco da ponte HPS-FPGA onde nao ha
 * componente trava o barramento -- a placa some ate ser religada. Use so com
 * o bitstream que tem o componente gravado.
 */
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/mman.h>
#include <unistd.h>

int main(int argc, char **argv) {
    if (argc < 2 || argc > 4) {
        fprintf(stderr, "uso: %s ENDERECO [32 [VALOR]]\n", argv[0]);
        return 2;
    }
    unsigned long endereco = strtoul(argv[1], NULL, 0);
    if (argc >= 3 && strtoul(argv[2], NULL, 0) != 32) {
        fprintf(stderr, "so 32 bits\n");
        return 2;
    }
    if (endereco % 4) {
        fprintf(stderr, "endereco precisa ser multiplo de 4\n");
        return 2;
    }

    int fd = open("/dev/mem", O_RDWR | O_SYNC);
    if (fd < 0) {
        perror("/dev/mem (rode como root)");
        return 1;
    }
    long pagina = sysconf(_SC_PAGESIZE);
    unsigned long base = endereco & ~(unsigned long)(pagina - 1);
    void *mapa = mmap(NULL, pagina, PROT_READ | PROT_WRITE, MAP_SHARED, fd, base);
    if (mapa == MAP_FAILED) {
        perror("mmap");
        close(fd);
        return 1;
    }
    volatile uint32_t *reg = (volatile uint32_t *)((char *)mapa + (endereco - base));

    if (argc == 4)
        *reg = (uint32_t)strtoul(argv[3], NULL, 0);
    else
        printf("0x%08X\n", *reg);

    munmap(mapa, pagina);
    close(fd);
    return 0;
}
