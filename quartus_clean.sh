#!/bin/bash
# ============================================================================
# quartus_clean.sh
# Remove arquivos e pastas gerados/desnecessários de um projeto Quartus
# antes de fazer push para o GitHub.
#
# Uso: ./quartus_clean.sh [caminho_do_projeto]
#   Se nenhum caminho for fornecido, usa o diretório atual.
#
# ATENÇÃO: Este script DELETA arquivos permanentemente.
#          Faça backup antes de executar pela primeira vez.
# ============================================================================

set -euo pipefail

PROJECT_DIR="${1:-.}"

if [ ! -d "$PROJECT_DIR" ]; then
    echo "Erro: Diretório '$PROJECT_DIR' não encontrado."
    exit 1
fi

cd "$PROJECT_DIR"
echo "Limpando projeto Quartus em: $(pwd)"
echo "============================================"

# Contadores
removed_dirs=0
removed_files=0

remove_dir() {
    if [ -d "$1" ]; then
        echo "  [DIR]  Removendo $1/"
        rm -rf "$1"
        removed_dirs=$((removed_dirs + 1))
    fi
}

remove_file() {
    if [ -f "$1" ]; then
        echo "  [ARQ]  Removendo $1"
        rm -f "$1"
        removed_files=$((removed_files + 1))
    fi
}

# --- 1. Pastas inteiramente geradas ---
echo ""
echo ">> Removendo pastas geradas..."

remove_dir "db"
remove_dir "incremental_db"
remove_dir "output_files"
remove_dir "greybox_tmp"
remove_dir "stamp"

# --- 2. Arquivos gerados na raiz ---
echo ""
echo ">> Removendo arquivos gerados na raiz..."

remove_file "c5_pin_model_dump.txt"
remove_file "hps_sdram_p0_all_pins.txt"
remove_file "hps_sdram_p0_summary.csv"
remove_file "hps_clock_info.xml"
remove_file "soc_system_assignment_defaults.qdf"

# .sopcinfo — MANTIDOS (gerados pelo Qsys, não pela compilação;
# necessários para BSP, device tree e consistência com synthesis/)

# --- 3. Arquivos .bak ---
echo ""
echo ">> Removendo arquivos .bak..."

while IFS= read -r -d '' f; do
    echo "  [BAK]  Removendo $f"
    rm -f "$f"
    removed_files=$((removed_files + 1))
done < <(find . -name "*.bak" -print0 2>/dev/null)

# Pastas soc_system/ e fft_core/ — MANTIDAS integralmente
# (geradas pelo Platform Designer, mas necessárias para compilar
# sem precisar regenerar o Qsys)

# --- Resumo ---
echo ""
echo "============================================"
echo "Limpeza concluída!"
echo "  Pastas removidas:  $removed_dirs"
echo "  Arquivos removidos: $removed_files"
echo ""
echo "Próximo passo: adicione o .gitignore ao seu repositório"
echo "para evitar que esses arquivos voltem a ser commitados."
