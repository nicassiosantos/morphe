#!/bin/bash

# Default variables
PROJECT_DIR="."
RUN_MAP=0
RUN_FIT=0
RUN_ASM=0
RUN_STA=0
RUN_ALL=0
UPLOAD=0

# Help function
# Help function
show_help() {
    cat << 'EOF'
Usage: ./quartus_flow.sh [OPTIONS]

Quartus Prime compilation flow automation script, optimized for the DE1-SoC.

PROJECT OPTIONS:
  --dir <path>       Specify the Quartus project directory. 
                     (Default: Current working directory)
  --project <name>   Specify the Quartus project name.
                     (Default: Auto-detects the first .qpf file in the directory)
  --rev <name>       Specify the revision name.
                     (Default: Same as the project name)

COMPILATION STAGES:
  --map              Run Analysis & Synthesis (quartus_map). 
                     Elaborates the RTL design and performs logic synthesis.
  --fit              Run Fitter (quartus_fit). 
                     Performs place and route on the specific FPGA fabric.
  --asm              Run Assembler (quartus_asm). 
                     Generates the SRAM Object File (.sof) for device programming.
  --sta              Run Timing Analysis (quartus_sta). 
                     Verifies fmax and evaluates setup/hold timing constraints.
  --all              Run the complete compilation flow (map -> fit -> asm -> sta).

HARDWARE PROGRAMMING:
  --upload           Upload the generated .sof file to the FPGA via JTAG.
                     Requires the physical board to be connected and powered on.

MISCELLANEOUS:
  --help             Display this help message and exit.

EXAMPLES:
  Run the full flow and immediately upload the bitstream to the DE1-SoC:
    ./quartus_flow.sh --dir ../my_project --all --upload

  Compile only the synthesis and timing analysis on a specific project revision:
    ./quartus_flow.sh --project cpu_core --rev optimized_alu --map --sta

EOF
    exit 0
}

# Parse command-line arguments
while [[ "$#" -gt 0 ]]; do
    case $1 in
        --dir) PROJECT_DIR="$2"; shift ;;
        --project) PROJECT_NAME="$2"; shift ;;
        --rev) REVISION_NAME="$2"; shift ;;
        --map) RUN_MAP=1 ;;
        --fit) RUN_FIT=1 ;;
        --asm) RUN_ASM=1 ;;
        --sta) RUN_STA=1 ;;
        --all) RUN_ALL=1 ;;
        --upload) UPLOAD=1 ;;
        --help) show_help ;;
        *) echo "Unknown parameter passed: $1"; show_help ;;
    esac
    shift
done

# Change to the target directory
cd "$PROJECT_DIR" || { echo "Error: Directory $PROJECT_DIR not found."; exit 1; }

# Auto-detect project if not explicitly specified
if [ -z "$PROJECT_NAME" ]; then
    QPF_FILE=$(ls *.qpf 2>/dev/null | head -n 1)
    if [ -z "$QPF_FILE" ]; then
        echo "Error: No .qpf file found in $PROJECT_DIR. Please specify with --project."
        exit 1
    fi
    PROJECT_NAME="${QPF_FILE%.*}"
fi

if [ -z "$REVISION_NAME" ]; then
    REVISION_NAME="$PROJECT_NAME"
fi

echo "--- Quartus Flow: $PROJECT_NAME (Rev: $REVISION_NAME) in $PROJECT_DIR ---"

# Set flags if --all is used
if [ "$RUN_ALL" -eq 1 ]; then
    RUN_MAP=1; RUN_FIT=1; RUN_ASM=1; RUN_STA=1
fi

# Exit if no actions were specified
if [ "$RUN_MAP" -eq 0 ] && [ "$RUN_FIT" -eq 0 ] && [ "$RUN_ASM" -eq 0 ] && [ "$RUN_STA" -eq 0 ] && [ "$UPLOAD" -eq 0 ]; then
    echo "No actions specified. Use --help to see available options."
    exit 1
fi

# --- Execution ---

if [ "$RUN_MAP" -eq 1 ]; then
    echo "[*] Running Analysis & Synthesis..."
    quartus_map --read_settings_files=on --write_settings_files=off "$PROJECT_NAME" -c "$REVISION_NAME" || exit 1
fi

if [ "$RUN_FIT" -eq 1 ]; then
    echo "[*] Running Fitter..."
    quartus_fit --read_settings_files=on --write_settings_files=off "$PROJECT_NAME" -c "$REVISION_NAME" || exit 1
fi

if [ "$RUN_ASM" -eq 1 ]; then
    echo "[*] Running Assembler..."
    quartus_asm --read_settings_files=on --write_settings_files=off "$PROJECT_NAME" -c "$REVISION_NAME" || exit 1
fi

if [ "$RUN_STA" -eq 1 ]; then
    echo "[*] Running Timing Analysis..."
    quartus_sta "$PROJECT_NAME" -c "$REVISION_NAME" || exit 1
fi

if [ "$UPLOAD" -eq 1 ]; then
    echo "[*] Uploading .sof to FPGA via JTAG..."
    
    # Check both the root and output_files/ directories for the .sof
    SOF_FILE="output_files/$REVISION_NAME.sof"
    [ -f "$REVISION_NAME.sof" ] && SOF_FILE="$REVISION_NAME.sof"

    if [ ! -f "$SOF_FILE" ]; then
         echo "Error: .sof file not found. Did you run the assembler (--asm) first?"
         exit 1
    fi

    # Detect the USB-Blaster
    CABLE_NAME=$(quartus_pgm -l | grep "USB-Blaster" | head -n 1 | cut -d ' ' -f 2)
    if [ -z "$CABLE_NAME" ]; then
        echo "Error: USB-Blaster not found. Is the board turned on and connected?"
        exit 1
    fi
    
    # Upload
    quartus_pgm -m jtag -c "$CABLE_NAME" -o "p;$SOF_FILE"
fi

echo "--- Done! ---"