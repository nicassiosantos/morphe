# Makefile para o servidor Morphe no HPS da DE1-SoC.
#
# Uso típico:
#   make                 # compila nativamente (rodar direto no Linaro do HPS)
#   make CROSS=arm-linux-gnueabihf-   # cross-compile desde o PC
#   make clean
#
# Por padrão o binário é 'morphe_server'.
#
# OTIMIZACAO PARA O CORTEX-A9 DA DE1-SOC:
# O target hardware e o Cortex-A9 (ARMv7-A com VFPv3-D32 e NEON). As flags
# abaixo habilitam:
#   -O3                          : auto-vetorizacao agressiva
#   -mcpu=cortex-a9              : agendamento de instrucoes especifico do A9
#   -mfpu=neon                   : permite NEON SIMD (4 floats em paralelo)
#   -mfloat-abi=hard             : passa floats em registradores VFP (mais rapido)
#   -ftree-vectorize             : forca o passe de vetorizacao do GCC
#   -funsafe-math-optimizations  : permite reordenacao FP (necessario para
#                                  vetorizacao agressiva de loops com multiply)
#
# Para inspecionar o que foi vetorizado durante o build, descomente o
# -fopt-info-vec abaixo. Loops nao-vetorizaveis aparecem como "missed".

CROSS    ?=
CC       := $(CROSS)gcc

# Detecta se o target e ARM. Se sim, ativa NEON. Caso contrario (x86 host
# para morphe_testserver), usa apenas -O3 generico.
ARCH := $(shell $(CC) -dumpmachine 2>/dev/null)
IS_ARM := $(if $(findstring arm,$(ARCH)),1,)

CFLAGS_COMMON := -O3 -Wall -Wextra -Wno-unused-parameter -std=gnu99 -D_GNU_SOURCE \
                 -ftree-vectorize -funsafe-math-optimizations
CFLAGS_ARM    := -mcpu=cortex-a9 -mfpu=neon -mfloat-abi=hard

ifeq ($(IS_ARM),1)
    CFLAGS := $(CFLAGS_COMMON) $(CFLAGS_ARM)
else
    CFLAGS := $(CFLAGS_COMMON)
endif

# Para inspecionar o que foi vetorizado, descomente:
# CFLAGS += -fopt-info-vec (-ftree-vectorizer-verbose=2 por causa da versão do gcc)

LDFLAGS  :=
LDLIBS   := -lm -lrt

TARGET       := morphe_server
TESTSERVER   := morphe_testserver

HEADERS_PROD := morphe_protocol.h morphe_config.h hps_0.h address_map_arm.h
HEADERS_TEST := morphe_protocol.h morphe_config.h

.PHONY: all clean run testserver test info

# 'all' compila apenas o que estiver presente. testserver e test_wire sao
# opcionais -- se o arquivo .c nao existir, sao silenciosamente pulados.
TESTSERVER_SRC := $(wildcard morphe_testserver.c)
TESTWIRE_SRC   := $(wildcard test_wire.c)

ifneq ($(TESTSERVER_SRC),)
all: $(TARGET) $(TESTSERVER)
else
all: $(TARGET)
endif

# Servidor de produção (depende dos headers do hps_0)
$(TARGET): morphe_server.c $(HEADERS_PROD)
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ morphe_server.c $(LDLIBS)

# Servidor de teste (sem /dev/mem, sem hps_0 — rodável no PC)
$(TESTSERVER): morphe_testserver.c $(HEADERS_TEST)
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ morphe_testserver.c $(LDLIBS)

# Teste unitário do wire format
test_wire: test_wire.c $(HEADERS_TEST)
	$(CC) $(CFLAGS) -o $@ test_wire.c

test: test_wire
	./test_wire

clean:
	rm -f *.o $(TARGET) $(TESTSERVER) test_wire morphe_server.s

run: $(TARGET)
	sudo ./$(TARGET)

run-test: $(TESTSERVER)
	./$(TESTSERVER)

# Diagnostico: imprime CFLAGS resolvidos
info:
	@echo "Compilador:  $(CC)"
	@echo "Target arch: $(ARCH)"
	@echo "IS_ARM:      $(if $(IS_ARM),sim (NEON ativo),nao (NEON desativado))"
	@echo "CFLAGS:      $(CFLAGS)"

# Gera assembly anotado para inspecionar a vetorizacao manualmente.
# Uso:  make morphe_server.s
#       grep -E 'q[0-9]|d[0-9]|vmul|vld1|vst1' morphe_server.s | head -50
# Linhas com registradores q0-q15 ou instrucoes vmul/vld1 confirmam NEON.
%.s: %.c
	$(CC) $(CFLAGS) -S -ftree-vectorizer-verbose=2 -o $@ $<
