// ============================================================================
// Copyright (c) 2013 by Terasic Technologies Inc.
// ============================================================================
//
// Permission:
//
//   Terasic grants permission to use and modify this code for use
//   in synthesis for all Terasic Development Boards and Altera Development 
//   Kits made by Terasic.  Other use of this code, including the selling 
//   ,duplication, or modification of any portion is strictly prohibited.
//
// Disclaimer:
//
//   This VHDL/Verilog or C/C++ source code is intended as a design reference
//   which illustrates how these types of functions can be implemented.
//   It is the user's responsibility to verify their design for
//   consistency and functionality through the use of formal
//   verification methods.  Terasic provides no warranty regarding the use 
//   or functionality of this code.
//
// ============================================================================
//           
//  Terasic Technologies Inc
//  9F., No.176, Sec.2, Gongdao 5th Rd, East Dist, Hsinchu City, 30070. Taiwan
//  
//  
//                     web: http://www.terasic.com/  
//                     email: support@terasic.com
//
// ============================================================================
//Date:  Mon Jun 17 20:35:29 2013
// ============================================================================

`define ENABLE_HPS

module ghrd_top(

      ///////// ADC /////////
      output             ADC_CONVST,
      output             ADC_DIN,
      input              ADC_DOUT,
      output             ADC_SCLK,

      ///////// AUD /////////
      input              AUD_ADCDAT,
      inout              AUD_ADCLRCK,
      inout              AUD_BCLK,
      output             AUD_DACDAT,
      inout              AUD_DACLRCK,
      output             AUD_XCK,

      ///////// CLOCK2 /////////
      input              CLOCK2_50,

      ///////// CLOCK3 /////////
      input              CLOCK3_50,

      ///////// CLOCK4 /////////
      input              CLOCK4_50,

      ///////// CLOCK /////////
      input              CLOCK_50,

      ///////// DRAM /////////
      output      [12:0] DRAM_ADDR,
      output      [1:0]  DRAM_BA,
      output             DRAM_CAS_N,
      output             DRAM_CKE,
      output             DRAM_CLK,
      output             DRAM_CS_N,
      inout       [15:0] DRAM_DQ,
      output             DRAM_LDQM,
      output             DRAM_RAS_N,
      output             DRAM_UDQM,
      output             DRAM_WE_N,

      ///////// FAN /////////
      output             FAN_CTRL,

      ///////// FPGA /////////
      output             FPGA_I2C_SCLK,
      inout              FPGA_I2C_SDAT,

      ///////// GPIO /////////
      inout     [35:0]         GPIO_0,
      inout     [35:0]         GPIO_1,
 
      ///////// HEX0 /////////
      output      [6:0]  HEX0,

      ///////// HEX1 /////////
      output      [6:0]  HEX1,

      ///////// HEX2 /////////
      output      [6:0]  HEX2,

      ///////// HEX3 /////////
      output      [6:0]  HEX3,

      ///////// HEX4 /////////
      output      [6:0]  HEX4,

      ///////// HEX5 /////////
      output      [6:0]  HEX5,

`ifdef ENABLE_HPS
      ///////// HPS /////////
      inout              HPS_CONV_USB_N,
      output      [14:0] HPS_DDR3_ADDR,
      output      [2:0]  HPS_DDR3_BA,
      output             HPS_DDR3_CAS_N,
      output             HPS_DDR3_CKE,
      output             HPS_DDR3_CK_N,
      output             HPS_DDR3_CK_P,
      output             HPS_DDR3_CS_N,
      output      [3:0]  HPS_DDR3_DM,
      inout       [31:0] HPS_DDR3_DQ,
      inout       [3:0]  HPS_DDR3_DQS_N,
      inout       [3:0]  HPS_DDR3_DQS_P,
      output             HPS_DDR3_ODT,
      output             HPS_DDR3_RAS_N,
      output             HPS_DDR3_RESET_N,
      input              HPS_DDR3_RZQ,
      output             HPS_DDR3_WE_N,
      output             HPS_ENET_GTX_CLK,
      inout              HPS_ENET_INT_N,
      output             HPS_ENET_MDC,
      inout              HPS_ENET_MDIO,
      input              HPS_ENET_RX_CLK,
      input       [3:0]  HPS_ENET_RX_DATA,
      input              HPS_ENET_RX_DV,
      output      [3:0]  HPS_ENET_TX_DATA,
      output             HPS_ENET_TX_EN,
      inout       [3:0]  HPS_FLASH_DATA,
      output             HPS_FLASH_DCLK,
      output             HPS_FLASH_NCSO,
      inout              HPS_GSENSOR_INT,
      inout              HPS_I2C1_SCLK,
      inout              HPS_I2C1_SDAT,
      inout              HPS_I2C2_SCLK,
      inout              HPS_I2C2_SDAT,
      inout              HPS_I2C_CONTROL,
      inout              HPS_KEY,
      inout              HPS_LED,
      inout              HPS_LTC_GPIO,
      output             HPS_SD_CLK,
      inout              HPS_SD_CMD,
      inout       [3:0]  HPS_SD_DATA,
      output             HPS_SPIM_CLK,
      input              HPS_SPIM_MISO,
      output             HPS_SPIM_MOSI,
      inout              HPS_SPIM_SS,
      input              HPS_UART_RX,
      output             HPS_UART_TX,
      input              HPS_USB_CLKOUT,
      inout       [7:0]  HPS_USB_DATA,
      input              HPS_USB_DIR,
      input              HPS_USB_NXT,
      output             HPS_USB_STP,
`endif /*ENABLE_HPS*/

      ///////// IRDA /////////
      input              IRDA_RXD,
      output             IRDA_TXD,

      ///////// KEY /////////
      input       [3:0]  KEY,

      ///////// LEDR /////////
      output      [9:0]  LEDR,

      ///////// PS2 /////////
      inout              PS2_CLK,
      inout              PS2_CLK2,
      inout              PS2_DAT,
      inout              PS2_DAT2,

      ///////// SW /////////
      input       [9:0]  SW,

      ///////// TD /////////
      input              TD_CLK27,
      input      [7:0]  TD_DATA,
      input              TD_HS,
      output             TD_RESET_N,
      input              TD_VS,

      ///////// VGA /////////
      output      [7:0]  VGA_B,
      output             VGA_BLANK_N,
      output             VGA_CLK,
      output      [7:0]  VGA_G,
      output             VGA_HS,
      output      [7:0]  VGA_R,
      output             VGA_SYNC_N,
      output             VGA_VS,

      ///////// UART /////////	
      output             UART_TX,
      input              UART_RX,
      output             UART_RTS,
      input              UART_CTS,

      ///////// QSPI /////////	
      output             QSPI_FLASH_SCLK,
      inout   [ 3: 0]    QSPI_FLASH_DATA,
      output             QSPI_FLASH_CE_n,

      ///////// RISC-V JTAG /////////
      input              RISCV_JTAG_TCK,
      input              RISCV_JTAG_TDI,
      output             RISCV_JTAG_TDO,
      input              RISCV_JTAG_TMS 
);

// internal wires and registers declaration
wire [3:0]  fpga_debounced_buttons;
wire [9:0]  fpga_led_internal;
wire        hps_fpga_reset_n;
wire [2:0]  hps_reset_req;
wire        hps_cold_reset;
wire        hps_warm_reset;
wire        hps_debug_reset;
wire [27:0] stm_hw_events;

// connection of internal logics
assign stm_hw_events = {{3{1'b0}}, SW, fpga_led_internal, fpga_debounced_buttons};

/* ===========================================================================================
 * ===========================================================================================
 * CUSTOM DSP ACCELERATORS
 * ===========================================================================================
 * =========================================================================================== */

/* -------------------------------------------------------------------------------------------
 * 1. GLOBAL PARAMETERS
 * ------------------------------------------------------------------------------------------- */
// --- FFT Parameters ---
localparam FFT_CLOG4_DATA_WIDTH = 4;
localparam FFT_DATA_WIDTH       = 32;
localparam FFT_ADDRESS_WIDTH    = 10;

// --- FIR Parameters ---
// Integer: +-32767 | Float: ~0.000015
localparam FIR_DATA_WIDTH    = 32;
localparam FIR_XN_ADDR_WIDTH = 10;
localparam FIR_HN_ADDR_WIDTH = 10;
localparam FIR_YN_ADDR_WIDTH = FIR_XN_ADDR_WIDTH + 1;
localparam FIR_XN_LENGTH     = 1024;
localparam FIR_HN_LENGTH     = 1024;
localparam FIR_YN_LENGTH     = FIR_XN_LENGTH + FIR_HN_LENGTH - 1;

localparam FIR_SAMPLE_COUNT  = 1024;
localparam FIR_SAMPLE_PERIOD = 96;   // 50 MHz / 0.52 MSPS

// --- CONV1D Parameters (Fixed point Q16.16 signed) ---
// Integer: +-32767 | Float: ~0.000015
// --- IIR (cascata de secoes de 2a ordem) ---
localparam IIR_DATA_WIDTH      = 32;
localparam IIR_ADDR_WIDTH      = 10;    // 1024 amostras
localparam IIR_COEF_ADDR_WIDTH = 8;     // 256 palavras = ate 51 secoes
localparam IIR_N_SAMPLES       = 1024;
localparam IIR_MAX_SECOES      = 16;    // ordem 32; o estudo nunca passou de 11

localparam CONV1d_DATA_WIDTH    = 32;
localparam CONV1d_XN_ADDR_WIDTH = 10;
localparam CONV1d_HN_ADDR_WIDTH = 10;
localparam CONV1d_YN_ADDR_WIDTH = CONV1d_XN_ADDR_WIDTH + 1;
localparam CONV1d_XN_LENGTH     = 1024;
localparam CONV1d_HN_LENGTH     = 1024;
localparam CONV1d_YN_LENGTH     = CONV1d_XN_LENGTH + CONV1d_HN_LENGTH - 1;


/* -------------------------------------------------------------------------------------------
 * 2. FFT PERIPHERAL SIGNALS
 * ------------------------------------------------------------------------------------------- */
// --- Control & Status ---
wire                      fft_inverse;
wire                      fft_wrapper_start;
wire                      fft_wrapper_done;
wire [5:0]                fft_bfp_exponent;

wire                      reset_n_hn = 1'b1;
wire                      reset_n_xn = 1'b1;
wire                      reset_n_yn = 1'b1;

// --- SRAM Interface: X[n] Real ---
wire [FFT_ADDRESS_WIDTH-1:0]    fft_xn_re_address;
wire                            fft_xn_re_clken;
wire                            fft_xn_re_chipselect;
wire                            fft_xn_re_write;
wire [FFT_DATA_WIDTH-1:0]       fft_xn_re_readdata;
wire [FFT_DATA_WIDTH-1:0]       fft_xn_re_writedata;
wire [FFT_CLOG4_DATA_WIDTH-1:0] fft_xn_re_byteenable = {FFT_CLOG4_DATA_WIDTH{1'b1}};

// --- SRAM Interface: X[n] Imaginary ---
wire [FFT_ADDRESS_WIDTH-1:0]    fft_xn_imag_address;
wire                            fft_xn_imag_clken;
wire                            fft_xn_imag_chipselect;
wire                            fft_xn_imag_write;
wire [FFT_DATA_WIDTH-1:0]       fft_xn_imag_readdata;
wire [FFT_DATA_WIDTH-1:0]       fft_xn_imag_writedata;
wire [FFT_CLOG4_DATA_WIDTH-1:0] fft_xn_imag_byteenable = {FFT_CLOG4_DATA_WIDTH{1'b1}};

// --- SRAM Interface: Y[n] Real ---
wire [FFT_ADDRESS_WIDTH-1:0]    fft_yn_re_address;
wire                            fft_yn_re_clken;
wire                            fft_yn_re_chipselect;
wire                            fft_yn_re_write;
wire [FFT_DATA_WIDTH-1:0]       fft_yn_re_readdata;
wire [FFT_DATA_WIDTH-1:0]       fft_yn_re_writedata;
wire [FFT_CLOG4_DATA_WIDTH-1:0] fft_yn_re_byteenable = {FFT_CLOG4_DATA_WIDTH{1'b1}};

// --- SRAM Interface: Y[n] Imaginary ---
wire [FFT_ADDRESS_WIDTH-1:0]    fft_yn_imag_address;
wire                            fft_yn_imag_clken;
wire                            fft_yn_imag_chipselect;
wire                            fft_yn_imag_write;
wire [FFT_DATA_WIDTH-1:0]       fft_yn_imag_readdata;
wire [FFT_DATA_WIDTH-1:0]       fft_yn_imag_writedata;
wire [FFT_CLOG4_DATA_WIDTH-1:0] fft_yn_imag_byteenable = {FFT_CLOG4_DATA_WIDTH{1'b1}};


/* -------------------------------------------------------------------------------------------
 * 3. CONV1D PERIPHERAL SIGNALS
 * ------------------------------------------------------------------------------------------- */
// --- Control & Status ---
wire                            conv1d_start;
wire                            conv1d_done;
//assign LEDR[0] = conv1d_start;
//assign LEDR[1] = conv1d_done;

// --- SRAM Interface: X[n] ---
wire [CONV1d_XN_ADDR_WIDTH-1:0] conv1d_xn_address;
wire                            conv1d_xn_clken;
wire                            conv1d_xn_chipselect;
wire                            conv1d_xn_write;
wire [CONV1d_DATA_WIDTH-1:0]    conv1d_xn_readdata;
wire [CONV1d_DATA_WIDTH-1:0]    conv1d_xn_writedata;
wire [3:0]                      conv1d_xn_byteenable = 4'b1111;

// --- SRAM Interface: H[n] ---
wire [CONV1d_HN_ADDR_WIDTH-1:0] conv1d_hn_address;
wire                            conv1d_hn_clken;
wire                            conv1d_hn_chipselect;
wire                            conv1d_hn_write;
wire [CONV1d_DATA_WIDTH-1:0]    conv1d_hn_readdata;
wire [CONV1d_DATA_WIDTH-1:0]    conv1d_hn_writedata;
wire [3:0]                      conv1d_hn_byteenable = 4'b1111;

// --- SRAM Interface: Y[n] ---
wire [CONV1d_YN_ADDR_WIDTH-1:0] conv1d_yn_address;
wire                            conv1d_yn_clken;
wire                            conv1d_yn_chipselect;
wire                            conv1d_yn_write;
wire [CONV1d_DATA_WIDTH-1:0]    conv1d_yn_readdata;
wire [CONV1d_DATA_WIDTH-1:0]    conv1d_yn_writedata;
wire [3:0]                      conv1d_yn_byteenable = 4'b1111;


/* -------------------------------------------------------------------------------------------
 * 3-bis. IIR CASCADE PERIPHERAL SIGNALS
 * ------------------------------------------------------------------------------------------- */
// --- Controle e status ---
wire                              iir_start;
wire                              iir_done;
wire                              iir_error;
wire [4:0]                        iir_nsecoes;

// --- SRAM de entrada x[n] ---
wire [IIR_ADDR_WIDTH-1:0]         iir_xn_address;
wire                              iir_xn_clken;
wire                              iir_xn_chipselect;
wire                              iir_xn_write;
wire [IIR_DATA_WIDTH-1:0]         iir_xn_readdata;
wire [IIR_DATA_WIDTH-1:0]         iir_xn_writedata;
wire [3:0]                        iir_xn_byteenable = 4'b1111;

// --- SRAM dos coeficientes: 5 palavras por secao ---
wire [IIR_COEF_ADDR_WIDTH-1:0]    iir_coef_address;
wire                              iir_coef_clken;
wire                              iir_coef_chipselect;
wire                              iir_coef_write;
wire [IIR_DATA_WIDTH-1:0]         iir_coef_readdata;
wire [IIR_DATA_WIDTH-1:0]         iir_coef_writedata;
wire [3:0]                        iir_coef_byteenable = 4'b1111;

// --- SRAM de saida y[n] ---
wire [IIR_ADDR_WIDTH-1:0]         iir_yn_address;
wire                              iir_yn_clken;
wire                              iir_yn_chipselect;
wire                              iir_yn_write;
wire [IIR_DATA_WIDTH-1:0]         iir_yn_readdata;
wire [IIR_DATA_WIDTH-1:0]         iir_yn_writedata;
wire [3:0]                        iir_yn_byteenable = 4'b1111;


/* -------------------------------------------------------------------------------------------
 * 4. FIR WRAPPER PERIPHERAL SIGNALS
 * ------------------------------------------------------------------------------------------- */
// --- Control & Status ---
wire                             fir_start;
wire                             fir_done;
wire                             fir_error;

// --- SRAM Interface: X[n] — entrada do FIR (leitura pelo wrapper, escrita pela HPS) ---
wire [FIR_XN_ADDR_WIDTH-1:0]     fir_xn_address;
wire                             fir_xn_clken;
wire                             fir_xn_chipselect;
wire                             fir_xn_write;
wire [FIR_DATA_WIDTH-1:0]        fir_xn_readdata;
wire [FIR_DATA_WIDTH-1:0]        fir_xn_writedata;
wire [3:0]                       fir_xn_byteenable = 4'b1111; // Updated to 4 bytes for 32-bit data

// --- SRAM Interface: H[n] — coeficientes do FIR (leitura pelo wrapper, escrita pela HPS) ---
wire [FIR_HN_ADDR_WIDTH-1:0]     fir_hn_address;
wire                             fir_hn_clken;
wire                             fir_hn_chipselect;
wire                             fir_hn_write;
wire [FIR_DATA_WIDTH-1:0]        fir_hn_readdata;
wire [FIR_DATA_WIDTH-1:0]        fir_hn_writedata;
wire [3:0]                       fir_hn_byteenable = 4'b1111; // Updated to 4 bytes for 32-bit data

// --- SRAM Interface: Y[n] — saída do FIR (escrita pelo wrapper, leitura pela HPS) ---
wire [FIR_YN_ADDR_WIDTH-1:0]     fir_yn_address;
wire                             fir_yn_clken;
wire                             fir_yn_chipselect;
wire                             fir_yn_write;
wire [FIR_DATA_WIDTH-1:0]        fir_yn_readdata;
wire [FIR_DATA_WIDTH-1:0]        fir_yn_writedata;
wire [3:0]                       fir_yn_byteenable = 4'b1111; // Updated to 4 bytes for 32-bit data



/* ===========================================================================================
 * ===========================================================================================
 * CUSTOM DSP MODULES (INSTANTIATIONS)
 * ===========================================================================================
 * =========================================================================================== */

/*
memory_write_controller #(
    .MEM_ADDRESS_N_BITS(10),
    .DATA_WIDTH(16)
) memory_write_controller_fft_xn_re (
    .clk        (CLOCK_50),
    .reset_n    (reset_n_xn),
    .start_write(!KEY[0]),
    .data_in_addr(10'd_1023),
    .data_in    (16'h_31),

    .mem_address (fft_xn_re_address),
    .mem_wdata   (fft_xn_re_writedata),
    .mem_write   (fft_xn_re_write),
    .write_done  (HEX5[0]),
    .clken       (fft_xn_re_clken),
    .chipselect  (fft_xn_re_chipselect)
);

memory_write_controller #(
    .MEM_ADDRESS_N_BITS(10),
    .DATA_WIDTH(16)
) memory_write_controller_fft_xn_imag (
    .clk        (CLOCK_50),
    .reset_n    (reset_n_xn),
    .start_write(!KEY[1]),
    .data_in_addr(10'd_1023),
    .data_in    (16'h_17),

    .mem_address (fft_xn_imag_address),
    .mem_wdata   (fft_xn_imag_writedata),
    .mem_write   (fft_xn_imag_write),
    .write_done  (HEX5[1]),
    .clken       (fft_xn_imag_clken),
    .chipselect  (fft_xn_imag_chipselect)
);

memory_write_controller #(
    .MEM_ADDRESS_N_BITS(10),
    .DATA_WIDTH(16)
) memory_write_controller_fft_yn_re (
    .clk        (CLOCK_50),
    .reset_n    (reset_n_yn),
    .start_write(!KEY[2]),
    .data_in_addr(10'd_1023),
    .data_in    (16'h_19),

    .mem_address (fft_yn_re_address),
    .mem_wdata   (fft_yn_re_writedata),
    .mem_write   (fft_yn_re_write),
    .write_done  (HEX5[2]),
    .clken       (fft_yn_re_clken),
    .chipselect  (fft_yn_re_chipselect)
);

memory_write_controller #(
    .MEM_ADDRESS_N_BITS(10),
    .DATA_WIDTH(16)
) memory_write_controller_fft_yn_imag (
    .clk        (CLOCK_50),
    .reset_n    (reset_n_yn),
    .start_write(!KEY[3]),
    .data_in_addr(10'd_1023),
    .data_in    (16'h_23),

    .mem_address (fft_yn_imag_address),
    .mem_wdata   (fft_yn_imag_writedata),
    .mem_write   (fft_yn_imag_write),
    .write_done  (HEX5[3]),
    .clken       (fft_yn_imag_clken),
    .chipselect  (fft_yn_imag_chipselect)
);

memory_write_controller #(
    .MEM_ADDRESS_N_BITS(10),
    .DATA_WIDTH(12)
) memory_write_controller_fft_yn_imag (
    .clk        (CLOCK_50),
    .reset_n    (reset_n_yn),
    .start_write(!KEY[3]),
    .data_in_addr(10'd_1023),
    .data_in    (adc_ch0),

    .mem_address (fft_yn_imag_address),
    .mem_wdata   (fft_yn_imag_writedata),
    .mem_write   (fft_yn_imag_write),
    .write_done  (HEX5[3]),
    .clken       (fft_yn_imag_clken),
    .chipselect  (fft_yn_imag_chipselect)
);
*/

conv1d #(
    .DATA_WIDTH     (CONV1d_DATA_WIDTH),
    .XN_LENGTH      (CONV1d_XN_LENGTH),
    .HN_LENGTH      (CONV1d_HN_LENGTH),
    .YN_LENGTH      (CONV1d_YN_LENGTH), // XN_LENGTH + HN_LENGTH - 1
    .XN_ADDR_N_BITS (CONV1d_XN_ADDR_WIDTH),
    .HN_ADDR_N_BITS (CONV1d_HN_ADDR_WIDTH),
    .YN_ADDR_N_BITS (CONV1d_YN_ADDR_WIDTH)
) u_conv1d (
    .clk                (CLOCK_50),
    .reset_n            (hps_fpga_reset_n),

    // PIO de controle (Platform Designer)
    .start              (conv1d_start),       // bit 0 do PIO start (HPS -> FPGA)
    .done               (conv1d_done),        // bit 0 do PIO done  (FPGA -> HPS)

    // Interface SRAM de x[n] (leitura)
    .xn_sram_readdata   (conv1d_xn_readdata),
    .xn_sram_address    (conv1d_xn_address),
    .xn_sram_chipselect (conv1d_xn_chipselect),
    .xn_sram_clken      (conv1d_xn_clken),
    .xn_sram_write      (conv1d_xn_write),

    // Interface SRAM de h[n] (leitura)
    .hn_sram_readdata   (conv1d_hn_readdata),
    .hn_sram_address    (conv1d_hn_address),
    .hn_sram_chipselect (conv1d_hn_chipselect),
    .hn_sram_clken      (conv1d_hn_clken),
    .hn_sram_write      (conv1d_hn_write),

    // Interface SRAM de y[n] (escrita)
    .yn_sram_address    (conv1d_yn_address),
    .yn_sram_wdata      (conv1d_yn_writedata),
    .yn_sram_chipselect (conv1d_yn_chipselect),
    .yn_sram_clken      (conv1d_yn_clken),
    .yn_sram_write      (conv1d_yn_write)
);

/*
wire [11:0] adc_ch0;
assign LEDR[9:0] = adc_ch0[11:2];

adcltc2308_controller u_adc (
    .CLOCK    (CLOCK_50),           // external_interface.clk
    .RESET    (~hps_fpga_reset_n),  // external_interface.reset
    .ADC_SCLK (ADC_SCLK),           // external_interface.SCLK
    .ADC_CS_N (ADC_CONVST),         // external_interface.CS_N
    .ADC_DOUT (ADC_DOUT),           // external_interface.DOUT
    .ADC_DIN  (ADC_DIN),            // external_interface.DIN
    .CH0      (adc_ch0),            // readings.CH0
    .CH1      (),                   // readings.CH1
    .CH2      (),                   // readings.CH2
    .CH3      (),                   // readings.CH3
    .CH4      (),                   // readings.CH4
    .CH5      (),                   // readings.CH5
    .CH6      (),                   // readings.CH6
    .CH7      ()                    // readings.CH7
);
*/

wire [3:0] fft_debug_state;
assign LEDR[3:0] = fft_debug_state;
wire [3:0] fir_debug_state;
assign LEDR[7:4] = fir_debug_state;
assign LEDR[8]   = fir_done;
assign LEDR[9]   = fir_error;

// Temporarily mapping the SRAM output to the LEDs for debugging
// assign LEDR[9:0] = fft_xn_re_readdata[9:0];

// ===========================================================================================
// INSTANTIATION: FFT Wrapper
// ===========================================================================================
fft_wrapper #(
    .FFT_N      (1 << FFT_ADDRESS_WIDTH), // 1024 points (derived from 10 address bits)
    .SRAM_DATA_WIDTH(32),
    .FFT_DATA_WIDTH (24),         // 16 bits
    .ADDR_BITS  (FFT_ADDRESS_WIDTH),      // 10 bits
    .EXP_WIDTH  (6)
) u_fft_wrapper (
    .clk        (CLOCK_50),
    .reset_n    (hps_fpga_reset_n),

    // Interface de controle (PIOs do HPS)
    .start                  (fft_wrapper_start),
    .inverse                (fft_inverse),
    .done                   (fft_wrapper_done),
    .fft_exponent           (fft_bfp_exponent),

    // Input SRAM Real — porta B (leitura pelo FPGA)
    .in_real_mem_address    (fft_xn_re_address),
    .in_real_mem_write      (fft_xn_re_write),
    .in_real_clken          (fft_xn_re_clken),
    .in_real_chipselect     (fft_xn_re_chipselect),
    .in_real_sram_readdata  (fft_xn_re_readdata),

    // Input SRAM Imag — porta B (leitura pelo FPGA)
    .in_imag_mem_address    (fft_xn_imag_address),
    .in_imag_mem_write      (fft_xn_imag_write),
    .in_imag_clken          (fft_xn_imag_clken),
    .in_imag_chipselect     (fft_xn_imag_chipselect),
    .in_imag_sram_readdata  (fft_xn_imag_readdata),

    // Output SRAM Real — porta B (escrita pelo FPGA)
    .out_real_mem_address   (fft_yn_re_address),
    .out_real_mem_wdata     (fft_yn_re_writedata),
    .out_real_mem_write     (fft_yn_re_write),
    .out_real_clken         (fft_yn_re_clken),
    .out_real_chipselect    (fft_yn_re_chipselect),

    // Output SRAM Imag — porta B (escrita pelo FPGA)
    .out_imag_mem_address   (fft_yn_imag_address),
    .out_imag_mem_wdata     (fft_yn_imag_writedata),
    .out_imag_mem_write     (fft_yn_imag_write),
    .out_imag_clken         (fft_yn_imag_clken),
    .out_imag_chipselect    (fft_yn_imag_chipselect),

    // Debug (Optional)
    .debug_state            (fft_debug_state) // Leave unconnected if not routing to LEDs
);


// ===========================================================================================
// INSTANTIATION: FIR Wrapper
// NOTA: fir_xn e fir_yn precisam ser exportados no Platform Designer (soc_system)
//       como on-chip RAMs de 16 bits / 1024 palavras + PIOs de controle,
//       seguindo o mesmo padrão das SRAMs do FFT e conv1d.
// ===========================================================================================
/*fir_wrapper #(
    .SAMPLE_COUNT  (FIR_SAMPLE_COUNT),
    .ADDR_WIDTH    (FIR_ADDRESS_WIDTH),
    .SAMPLE_PERIOD (FIR_SAMPLE_PERIOD)
) u_fir_wrapper (
    .clk           (CLOCK_50),
    .rst_n         (hps_fpga_reset_n),

    // Controle (PIOs do Platform Designer)
    .start         (fir_start),
    .done          (fir_done),
    .error         (fir_error),

    // SRAM de entrada: X[n]
    .in_address    (fir_xn_address),
    .in_write      (fir_xn_write),
    .in_clken      (fir_xn_clken),
    .in_chipselect (fir_xn_chipselect),
    .in_readdata   (fir_xn_readdata),

    // SRAM de saída: Y[n]
    .out_address   (fir_yn_address),
    .out_write     (fir_yn_write),
    .out_clken     (fir_yn_clken),
    .out_chipselect(fir_yn_chipselect),
    .out_writedata (fir_yn_writedata),

    // Debug (mapeado em LEDR[7:4])
    .state_dbg     (fir_debug_state)
);
*/



// ===========================================================================================
// INSTANTIATION: IIR Cascade
// ===========================================================================================
// A saida y[n] tem o mesmo comprimento da entrada -- diferente do conv1d, em
// que y cresce para N+M-1. Filtro recursivo nao alonga o sinal.
iir_cascade #(
    .DATA_WIDTH       (IIR_DATA_WIDTH),
    .FRAC_BITS        (16),                    // Q15.16, o mesmo do conv1d
    .ACC_WIDTH        (72),
    .N_SAMPLES        (IIR_N_SAMPLES),
    .ADDR_N_BITS      (IIR_ADDR_WIDTH),
    .MAX_SECOES       (IIR_MAX_SECOES),
    .COEF_ADDR_N_BITS (IIR_COEF_ADDR_WIDTH)
) iir_inst (
    .clk       (CLOCK_50),
    .reset_n   (hps_fpga_reset_n),

    // PIOs de controle
    .start     (iir_start),          // HPS -> FPGA
    .done      (iir_done),           // FPGA -> HPS
    .error_sat (iir_error),          // FPGA -> HPS, saturou em alguma amostra
    .n_secoes  (iir_nsecoes[$clog2(IIR_MAX_SECOES+1)-1:0]),

    // SRAM dos coeficientes
    .coef_sram_readdata   (iir_coef_readdata),
    .coef_sram_address    (iir_coef_address),
    .coef_sram_chipselect (iir_coef_chipselect),
    .coef_sram_clken      (iir_coef_clken),
    .coef_sram_write      (iir_coef_write),

    // SRAM de x[n]
    .xn_sram_readdata     (iir_xn_readdata),
    .xn_sram_address      (iir_xn_address),
    .xn_sram_chipselect   (iir_xn_chipselect),
    .xn_sram_clken        (iir_xn_clken),
    .xn_sram_write        (iir_xn_write),

    // SRAM de y[n]
    .yn_sram_address      (iir_yn_address),
    .yn_sram_wdata        (iir_yn_writedata),
    .yn_sram_chipselect   (iir_yn_chipselect),
    .yn_sram_clken        (iir_yn_clken),
    .yn_sram_write        (iir_yn_write),

    .debug_state          ()
);

// ===========================================================================================
// INSTANTIATION: FIR Filter (using conv1d hardware accelerator)
// ===========================================================================================
conv1d #(
    .DATA_WIDTH     (FIR_DATA_WIDTH),
    .XN_LENGTH      (FIR_XN_LENGTH),
    .HN_LENGTH      (FIR_HN_LENGTH),
    .YN_LENGTH      (FIR_YN_LENGTH), // XN_LENGTH + HN_LENGTH - 1
    .XN_ADDR_N_BITS (FIR_XN_ADDR_WIDTH),
    .HN_ADDR_N_BITS (FIR_HN_ADDR_WIDTH),
    .YN_ADDR_N_BITS (FIR_YN_ADDR_WIDTH)
) fir_inst (
    .clk                (CLOCK_50),
    .reset_n            (hps_fpga_reset_n),

    // PIO de controle (Platform Designer)
    .start              (fir_start),          // HPS -> FPGA
    .done               (fir_done),           // FPGA -> HPS

    // Interface SRAM de x[n] (leitura da amostra)
    .xn_sram_readdata   (fir_xn_readdata),
    .xn_sram_address    (fir_xn_address),
    .xn_sram_chipselect (fir_xn_chipselect),
    .xn_sram_clken      (fir_xn_clken),
    .xn_sram_write      (fir_xn_write),

    // Interface SRAM de h[n] (leitura dos coeficientes do FIR)
    .hn_sram_readdata   (fir_hn_readdata),
    .hn_sram_address    (fir_hn_address),
    .hn_sram_chipselect (fir_hn_chipselect),
    .hn_sram_clken      (fir_hn_clken),
    .hn_sram_write      (fir_hn_write),

    // Interface SRAM de y[n] (escrita do resultado filtrado)
    .yn_sram_address    (fir_yn_address),
    .yn_sram_wdata      (fir_yn_writedata),
    .yn_sram_chipselect (fir_yn_chipselect),
    .yn_sram_clken      (fir_yn_clken),
    .yn_sram_write      (fir_yn_write)
);




/* ===========================================================================================
 * ===========================================================================================
 * PLATFORM DESIGNER SYSTEM (HPS-FPGA BRIDGE)
 * ===========================================================================================
 * =========================================================================================== */

soc_system u0 (
    // =======================================================================================
    //  CUSTOM DSP EXPORTS: FAST FOURIER TRANSFORM (FFT)
    // =======================================================================================
    // Control
    .fft_inverse_export       (fft_inverse),            // fft_inverse.export
    .fft_wrapper_start_export (fft_wrapper_start),      // fft_wrapper_start.export
    .fft_wrapper_done_export  (fft_wrapper_done),       // fft_wrapper_done.export  
    .fft_bfp_exponent_export  (fft_bfp_exponent),       // fft_bfp_exponent.export
    
    // Memory: X[n] Real
    .fft_xn_re_address        (fft_xn_re_address),      // fft_xn_re.address
    .fft_xn_re_clken          (fft_xn_re_clken),        //          .clken
    .fft_xn_re_chipselect     (fft_xn_re_chipselect),   //          .chipselect
    .fft_xn_re_write          (fft_xn_re_write),        //          .write
    .fft_xn_re_readdata       (fft_xn_re_readdata),     //          .readdata
    .fft_xn_re_writedata      (fft_xn_re_writedata),    //          .writedata
    .fft_xn_re_byteenable     (fft_xn_re_byteenable),   //          .byteenable
    
    // Memory: X[n] Imaginary
    .fft_xn_imag_address      (fft_xn_imag_address),    // fft_xn_imag.address
    .fft_xn_imag_clken        (fft_xn_imag_clken),      //            .clken
    .fft_xn_imag_chipselect   (fft_xn_imag_chipselect), //            .chipselect
    .fft_xn_imag_write        (fft_xn_imag_write),      //            .write
    .fft_xn_imag_readdata     (fft_xn_imag_readdata),   //            .readdata
    .fft_xn_imag_writedata    (fft_xn_imag_writedata),  //            .writedata
    .fft_xn_imag_byteenable   (fft_xn_imag_byteenable), //            .byteenable
    
    // Memory: Y[n] Real
    .fft_yn_re_address        (fft_yn_re_address),      // fft_yn_re.address
    .fft_yn_re_clken          (fft_yn_re_clken),        //          .clken
    .fft_yn_re_chipselect     (fft_yn_re_chipselect),   //          .chipselect
    .fft_yn_re_write          (fft_yn_re_write),        //          .write
    .fft_yn_re_readdata       (fft_yn_re_readdata),     //          .readdata
    .fft_yn_re_writedata      (fft_yn_re_writedata),    //          .writedata
    .fft_yn_re_byteenable     (fft_yn_re_byteenable),   //          .byteenable

    // Memory: Y[n] Imaginary
    .fft_yn_imag_address      (fft_yn_imag_address),    // fft_yn_imag.address
    .fft_yn_imag_clken        (fft_yn_imag_clken),      //            .clken
    .fft_yn_imag_chipselect   (fft_yn_imag_chipselect), //            .chipselect
    .fft_yn_imag_write        (fft_yn_imag_write),      //            .write
    .fft_yn_imag_readdata     (fft_yn_imag_readdata),   //            .readdata
    .fft_yn_imag_writedata    (fft_yn_imag_writedata),  //            .writedata
    .fft_yn_imag_byteenable   (fft_yn_imag_byteenable), //            .byteenable
    

    // =======================================================================================
    //  CUSTOM DSP EXPORTS: 1D CONVOLUTION
    // =======================================================================================
    // Control
    .conv1d_start_export      (conv1d_start),           // conv1d_start.export
    .conv1d_done_export       (conv1d_done),            // conv1d_done.export

    // Memory: X[n]
    .conv1d_xn_address        (conv1d_xn_address),      // conv1d_xn.address
    .conv1d_xn_clken          (conv1d_xn_clken),        //          .clken
    .conv1d_xn_chipselect     (conv1d_xn_chipselect),   //          .chipselect
    .conv1d_xn_write          (conv1d_xn_write),        //          .write
    .conv1d_xn_readdata       (conv1d_xn_readdata),     //          .readdata
    .conv1d_xn_writedata      (conv1d_xn_writedata),    //          .writedata
    .conv1d_xn_byteenable     (conv1d_xn_byteenable),   //          .byteenable
    
    // Memory: H[n]
    .conv1d_hn_address        (conv1d_hn_address),      // conv1d_hn.address
    .conv1d_hn_clken          (conv1d_hn_clken),        //          .clken
    .conv1d_hn_chipselect     (conv1d_hn_chipselect),   //          .chipselect
    .conv1d_hn_write          (conv1d_hn_write),        //          .write
    .conv1d_hn_readdata       (conv1d_hn_readdata),     //          .readdata
    .conv1d_hn_writedata      (conv1d_hn_writedata),    //          .writedata
    .conv1d_hn_byteenable     (conv1d_hn_byteenable),   //          .byteenable
    
    // Memory: Y[n]
    .conv1d_yn_address        (conv1d_yn_address),      // conv1d_yn.address
    .conv1d_yn_clken          (conv1d_yn_clken),        //          .clken
    .conv1d_yn_chipselect     (conv1d_yn_chipselect),   //          .chipselect
    .conv1d_yn_write          (conv1d_yn_write),        //          .write
    .conv1d_yn_readdata       (conv1d_yn_readdata),     //          .readdata
    .conv1d_yn_writedata      (conv1d_yn_writedata),    //          .writedata
    .conv1d_yn_byteenable     (conv1d_yn_byteenable),   //          .byteenable
    
    // =======================================================================================
    //  TODO: CUSTOM DSP EXPORTS: FIR WRAPPER
    //  Adicionar no Platform Designer (soc_system.qsys):
    //    - PIO 1-bit output : fir_start
    //    - PIO 1-bit input  : fir_done
    //    - PIO 1-bit input  : fir_error
    //    - On-chip RAM 16-bit x 1024: fir_xn  (porta A HPS r/w, porta B FPGA read)
    //    - On-chip RAM 16-bit x 1024: fir_yn  (porta A HPS read, porta B FPGA write)
    //  Após exportar, descomentar e preencher os connects abaixo:
    // =======================================================================================
    .fir_start_export       (fir_start),
    .fir_done_export        (fir_done),
    .fir_error_export       (fir_error),

    .fir_xn_address         (fir_xn_address),
    .fir_xn_clken           (fir_xn_clken),
    .fir_xn_chipselect      (fir_xn_chipselect),
    .fir_xn_write           (fir_xn_write),
    .fir_xn_readdata        (fir_xn_readdata),
    .fir_xn_writedata       (fir_xn_writedata),
    .fir_xn_byteenable      (fir_xn_byteenable),

    .fir_hn_address         (fir_hn_address),
    .fir_hn_clken           (fir_hn_clken),
    .fir_hn_chipselect      (fir_hn_chipselect),
    .fir_hn_write           (fir_hn_write),
    .fir_hn_readdata        (fir_hn_readdata),
    .fir_hn_writedata       (fir_hn_writedata),
    .fir_hn_byteenable      (fir_hn_byteenable),

    .fir_yn_address         (fir_yn_address),
    .fir_yn_clken           (fir_yn_clken),
    .fir_yn_chipselect      (fir_yn_chipselect),
    .fir_yn_write           (fir_yn_write),
    .fir_yn_readdata        (fir_yn_readdata),
    .fir_yn_writedata       (fir_yn_writedata),
    .fir_yn_byteenable      (fir_yn_byteenable),

    // ======================================================
    //  CUSTOM DSP EXPORTS: IIR
    // ======================================================
    .iir_start_export       (iir_start),
    .iir_done_export        (iir_done),
    .iir_error_export       (iir_error),
    .iir_nsecoes_export     (iir_nsecoes),

    .iir_xn_address          (iir_xn_address),
    .iir_xn_clken            (iir_xn_clken),
    .iir_xn_chipselect       (iir_xn_chipselect),
    .iir_xn_write            (iir_xn_write),
    .iir_xn_readdata         (iir_xn_readdata),
    .iir_xn_writedata        (iir_xn_writedata),
    .iir_xn_byteenable       (iir_xn_byteenable),

    .iir_coef_address        (iir_coef_address),
    .iir_coef_clken          (iir_coef_clken),
    .iir_coef_chipselect     (iir_coef_chipselect),
    .iir_coef_write          (iir_coef_write),
    .iir_coef_readdata       (iir_coef_readdata),
    .iir_coef_writedata      (iir_coef_writedata),
    .iir_coef_byteenable     (iir_coef_byteenable),

    .iir_yn_address          (iir_yn_address),
    .iir_yn_clken            (iir_yn_clken),
    .iir_yn_chipselect       (iir_yn_chipselect),
    .iir_yn_write            (iir_yn_write),
    .iir_yn_readdata         (iir_yn_readdata),
    .iir_yn_writedata        (iir_yn_writedata),
    .iir_yn_byteenable       (iir_yn_byteenable),


    
    // =======================================================================================
    //  STANDARD HPS/GHRD SIGNALS
    // =======================================================================================
    .clk_clk                               ( CLOCK_50           ),  //                            clk.clk
    .reset_reset_n                         ( hps_fpga_reset_n   ),  //                          reset.reset_n
    
    .memory_mem_a                          ( HPS_DDR3_ADDR  ),      //                         memory.mem_a
    .memory_mem_ba                         ( HPS_DDR3_BA    ),      //                               .mem_ba
    .memory_mem_ck                         ( HPS_DDR3_CK_P  ),      //                               .mem_ck
    .memory_mem_ck_n                       ( HPS_DDR3_CK_N  ),      //                               .mem_ck_n
    .memory_mem_cke                        ( HPS_DDR3_CKE   ),      //                               .mem_cke
    .memory_mem_cs_n                       ( HPS_DDR3_CS_N  ),      //                               .mem_cs_n
    .memory_mem_ras_n                      ( HPS_DDR3_RAS_N ),      //                               .mem_ras_n
    .memory_mem_cas_n                      ( HPS_DDR3_CAS_N ),      //                               .mem_cas_n
    .memory_mem_we_n                       ( HPS_DDR3_WE_N  ),      //                               .mem_we_n
    .memory_mem_reset_n                    ( HPS_DDR3_RESET_N   ),  //                               .mem_reset_n
    .memory_mem_dq                         ( HPS_DDR3_DQ    ),      //                               .mem_dq
    .memory_mem_dqs                        ( HPS_DDR3_DQS_P ),      //                               .mem_dqs
    .memory_mem_dqs_n                      ( HPS_DDR3_DQS_N ),      //                               .mem_dqs_n
    .memory_mem_odt                        ( HPS_DDR3_ODT   ),      //                               .mem_odt
    .memory_mem_dm                         ( HPS_DDR3_DM    ),      //                               .mem_dm
    .memory_oct_rzqin                      ( HPS_DDR3_RZQ   ),      //                               .oct_rzqin

    .hps_0_hps_io_hps_io_emac1_inst_TX_CLK ( HPS_ENET_GTX_CLK),     //                   hps_0_hps_io.hps_io_emac1_inst_TX_CLK
    .hps_0_hps_io_hps_io_emac1_inst_TXD0   ( HPS_ENET_TX_DATA[0] ), //                               .hps_io_emac1_inst_TXD0
    .hps_0_hps_io_hps_io_emac1_inst_TXD1   ( HPS_ENET_TX_DATA[1] ), //                               .hps_io_emac1_inst_TXD1
    .hps_0_hps_io_hps_io_emac1_inst_TXD2   ( HPS_ENET_TX_DATA[2] ), //                               .hps_io_emac1_inst_TXD2
    .hps_0_hps_io_hps_io_emac1_inst_TXD3   ( HPS_ENET_TX_DATA[3] ), //                               .hps_io_emac1_inst_TXD3
    .hps_0_hps_io_hps_io_emac1_inst_RXD0   ( HPS_ENET_RX_DATA[0] ), //                               .hps_io_emac1_inst_RXD0
    .hps_0_hps_io_hps_io_emac1_inst_MDIO   ( HPS_ENET_MDIO ),       //                               .hps_io_emac1_inst_MDIO
    .hps_0_hps_io_hps_io_emac1_inst_MDC    ( HPS_ENET_MDC  ),       //                               .hps_io_emac1_inst_MDC
    .hps_0_hps_io_hps_io_emac1_inst_RX_CTL ( HPS_ENET_RX_DV),       //                               .hps_io_emac1_inst_RX_CTL
    .hps_0_hps_io_hps_io_emac1_inst_TX_CTL ( HPS_ENET_TX_EN),       //                               .hps_io_emac1_inst_TX_CTL
    .hps_0_hps_io_hps_io_emac1_inst_RX_CLK ( HPS_ENET_RX_CLK),      //                               .hps_io_emac1_inst_RX_CLK
    .hps_0_hps_io_hps_io_emac1_inst_RXD1   ( HPS_ENET_RX_DATA[1] ), //                               .hps_io_emac1_inst_RXD1
    .hps_0_hps_io_hps_io_emac1_inst_RXD2   ( HPS_ENET_RX_DATA[2] ), //                               .hps_io_emac1_inst_RXD2
    .hps_0_hps_io_hps_io_emac1_inst_RXD3   ( HPS_ENET_RX_DATA[3] ), //                               .hps_io_emac1_inst_RXD3
    
    .hps_0_hps_io_hps_io_qspi_inst_IO0     ( HPS_FLASH_DATA[0]    ),//                               .hps_io_qspi_inst_IO0
    .hps_0_hps_io_hps_io_qspi_inst_IO1     ( HPS_FLASH_DATA[1]    ),//                               .hps_io_qspi_inst_IO1
    .hps_0_hps_io_hps_io_qspi_inst_IO2     ( HPS_FLASH_DATA[2]    ),//                               .hps_io_qspi_inst_IO2
    .hps_0_hps_io_hps_io_qspi_inst_IO3     ( HPS_FLASH_DATA[3]    ),//                               .hps_io_qspi_inst_IO3
    .hps_0_hps_io_hps_io_qspi_inst_SS0     ( HPS_FLASH_NCSO    ),   //                               .hps_io_qspi_inst_SS0
    .hps_0_hps_io_hps_io_qspi_inst_CLK     ( HPS_FLASH_DCLK    ),   //                               .hps_io_qspi_inst_CLK
    
    .hps_0_hps_io_hps_io_sdio_inst_CMD     ( HPS_SD_CMD    ),       //                               .hps_io_sdio_inst_CMD
    .hps_0_hps_io_hps_io_sdio_inst_D0      ( HPS_SD_DATA[0]     ),  //                               .hps_io_sdio_inst_D0
    .hps_0_hps_io_hps_io_sdio_inst_D1      ( HPS_SD_DATA[1]     ),  //                               .hps_io_sdio_inst_D1
    .hps_0_hps_io_hps_io_sdio_inst_CLK     ( HPS_SD_CLK   ),        //                               .hps_io_sdio_inst_CLK
    .hps_0_hps_io_hps_io_sdio_inst_D2      ( HPS_SD_DATA[2]     ),  //                               .hps_io_sdio_inst_D2
    .hps_0_hps_io_hps_io_sdio_inst_D3      ( HPS_SD_DATA[3]     ),  //                               .hps_io_sdio_inst_D3

    .hps_0_hps_io_hps_io_usb1_inst_D0      ( HPS_USB_DATA[0]    ),  //                               .hps_io_usb1_inst_D0
    .hps_0_hps_io_hps_io_usb1_inst_D1      ( HPS_USB_DATA[1]    ),  //                               .hps_io_usb1_inst_D1
    .hps_0_hps_io_hps_io_usb1_inst_D2      ( HPS_USB_DATA[2]    ),  //                               .hps_io_usb1_inst_D2
    .hps_0_hps_io_hps_io_usb1_inst_D3      ( HPS_USB_DATA[3]    ),  //                               .hps_io_usb1_inst_D3
    .hps_0_hps_io_hps_io_usb1_inst_D4      ( HPS_USB_DATA[4]    ),  //                               .hps_io_usb1_inst_D4
    .hps_0_hps_io_hps_io_usb1_inst_D5      ( HPS_USB_DATA[5]    ),  //                               .hps_io_usb1_inst_D5
    .hps_0_hps_io_hps_io_usb1_inst_D6      ( HPS_USB_DATA[6]    ),  //                               .hps_io_usb1_inst_D6
    .hps_0_hps_io_hps_io_usb1_inst_D7      ( HPS_USB_DATA[7]    ),  //                               .hps_io_usb1_inst_D7
    .hps_0_hps_io_hps_io_usb1_inst_CLK     ( HPS_USB_CLKOUT    ),   //                               .hps_io_usb1_inst_CLK
    .hps_0_hps_io_hps_io_usb1_inst_STP     ( HPS_USB_STP    ),      //                               .hps_io_usb1_inst_STP
    .hps_0_hps_io_hps_io_usb1_inst_DIR     ( HPS_USB_DIR    ),      //                               .hps_io_usb1_inst_DIR
    .hps_0_hps_io_hps_io_usb1_inst_NXT     ( HPS_USB_NXT    ),      //                               .hps_io_usb1_inst_NXT

    .hps_0_hps_io_hps_io_spim1_inst_CLK    ( HPS_SPIM_CLK   ),      //                               .hps_io_spim1_inst_CLK
    .hps_0_hps_io_hps_io_spim1_inst_MOSI   ( HPS_SPIM_MOSI ),       //                               .hps_io_spim1_inst_MOSI
    .hps_0_hps_io_hps_io_spim1_inst_MISO   ( HPS_SPIM_MISO ),       //                               .hps_io_spim1_inst_MISO
    .hps_0_hps_io_hps_io_spim1_inst_SS0    ( HPS_SPIM_SS ),         //                               .hps_io_spim1_inst_SS0

    .hps_0_hps_io_hps_io_uart0_inst_RX     ( HPS_UART_RX    ),      //                               .hps_io_uart0_inst_RX
    .hps_0_hps_io_hps_io_uart0_inst_TX     ( HPS_UART_TX    ),      //                               .hps_io_uart0_inst_TX
	
    .hps_0_hps_io_hps_io_i2c0_inst_SDA     ( HPS_I2C1_SDAT    ),    //                               .hps_io_i2c0_inst_SDA
    .hps_0_hps_io_hps_io_i2c0_inst_SCL     ( HPS_I2C1_SCLK    ),    //                               .hps_io_i2c0_inst_SCL
	
    .hps_0_hps_io_hps_io_i2c1_inst_SDA     ( HPS_I2C2_SDAT    ),    //                               .hps_io_i2c1_inst_SDA
    .hps_0_hps_io_hps_io_i2c1_inst_SCL     ( HPS_I2C2_SCLK    ),    //                               .hps_io_i2c1_inst_SCL
    
    .hps_0_hps_io_hps_io_gpio_inst_GPIO09  ( HPS_CONV_USB_N),       //                               .hps_io_gpio_inst_GPIO09
    .hps_0_hps_io_hps_io_gpio_inst_GPIO35  ( HPS_ENET_INT_N),       //                               .hps_io_gpio_inst_GPIO35
    .hps_0_hps_io_hps_io_gpio_inst_GPIO40  ( HPS_LTC_GPIO),         //                               .hps_io_gpio_inst_GPIO40
    .hps_0_hps_io_hps_io_gpio_inst_GPIO48  ( HPS_I2C_CONTROL),      //                               .hps_io_gpio_inst_GPIO48
    .hps_0_hps_io_hps_io_gpio_inst_GPIO53  ( HPS_LED),              //                               .hps_io_gpio_inst_GPIO53
    .hps_0_hps_io_hps_io_gpio_inst_GPIO54  ( HPS_KEY),              //                               .hps_io_gpio_inst_GPIO54
    .hps_0_hps_io_hps_io_gpio_inst_GPIO61  ( HPS_GSENSOR_INT),      //                               .hps_io_gpio_inst_GPIO61

    .hps_0_f2h_stm_hw_events_stm_hwevents  (stm_hw_events),         //        hps_0_f2h_stm_hw_events.stm_hwevents
    .hps_0_h2f_reset_reset_n               (hps_fpga_reset_n),      //                hps_0_h2f_reset.reset_n
    .hps_0_f2h_warm_reset_req_reset_n      (~hps_warm_reset),       //       hps_0_f2h_warm_reset_req.reset_n
    .hps_0_f2h_debug_reset_req_reset_n     (~hps_debug_reset),      //      hps_0_f2h_debug_reset_req.reset_n
    .hps_0_f2h_cold_reset_req_reset_n      (~hps_cold_reset)        //       hps_0_f2h_cold_reset_req.reset_n
);

// Source/Probe megawizard instance
hps_reset hps_reset_inst (
    .source_clk (CLOCK_50),
    .source     (hps_reset_req)
);

altera_edge_detector pulse_cold_reset (
    .clk       (CLOCK_50),
    .rst_n     (hps_fpga_reset_n),
    .signal_in (hps_reset_req[0]),
    .pulse_out (hps_cold_reset)
);

defparam pulse_cold_reset.PULSE_EXT = 6;
defparam pulse_cold_reset.EDGE_TYPE = 1;
defparam pulse_cold_reset.IGNORE_RST_WHILE_BUSY = 1;

altera_edge_detector pulse_warm_reset (
    .clk       (CLOCK_50),
    .rst_n     (hps_fpga_reset_n),
    .signal_in (hps_reset_req[1]),
    .pulse_out (hps_warm_reset)
);

defparam pulse_warm_reset.PULSE_EXT = 2;
defparam pulse_warm_reset.EDGE_TYPE = 1;
defparam pulse_warm_reset.IGNORE_RST_WHILE_BUSY = 1;

altera_edge_detector pulse_debug_reset (
    .clk       (CLOCK_50),
    .rst_n     (hps_fpga_reset_n),
    .signal_in (hps_reset_req[2]),
    .pulse_out (hps_debug_reset)
);

defparam pulse_debug_reset.PULSE_EXT = 32;
defparam pulse_debug_reset.EDGE_TYPE = 1;
defparam pulse_debug_reset.IGNORE_RST_WHILE_BUSY = 1;

endmodule
