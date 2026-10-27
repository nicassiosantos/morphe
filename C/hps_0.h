#ifndef _ALTERA_HPS_0_H_
#define _ALTERA_HPS_0_H_

/*
 * ARQUIVO GERADO -- nao editar a mao.
 *
 * Gerado por Quartus/gen_hps_header.py a partir de
 * 'soc_system.sopcinfo', modulo 'hps_0'.
 *
 * Para regenerar, da pasta Quartus/:
 *     python gen_hps_header.py
 *
 * Substitui o 'sopc-create-header-files' do SoC EDS. Se o projeto de
 * hardware mudar, rode de novo -- 'python gen_hps_header.py --check'
 * acusa divergencia sem escrever nada.
 */

/*
 * Dispositivos conectados aos masters:
 *   h2f_axi_master
 *   h2f_lw_axi_master
 */

/*
 * Macros for device 'onchip_memory2_0', class 'altera_avalon_onchip_memory2'
 * The macros are prefixed with 'ONCHIP_MEMORY2_0_'.
 */
#define ONCHIP_MEMORY2_0_COMPONENT_TYPE altera_avalon_onchip_memory2
#define ONCHIP_MEMORY2_0_COMPONENT_NAME onchip_memory2_0
#define ONCHIP_MEMORY2_0_BASE 0x0
#define ONCHIP_MEMORY2_0_SPAN 65536
#define ONCHIP_MEMORY2_0_END 0xffff

/*
 * Macros for device 'fft_yn_re', class 'altera_avalon_onchip_memory2'
 * The macros are prefixed with 'FFT_YN_RE_'.
 */
#define FFT_YN_RE_COMPONENT_TYPE altera_avalon_onchip_memory2
#define FFT_YN_RE_COMPONENT_NAME fft_yn_re
#define FFT_YN_RE_BASE 0x18000
#define FFT_YN_RE_SPAN 4096
#define FFT_YN_RE_END 0x18fff

/*
 * Macros for device 'fft_yn_imag', class 'altera_avalon_onchip_memory2'
 * The macros are prefixed with 'FFT_YN_IMAG_'.
 */
#define FFT_YN_IMAG_COMPONENT_TYPE altera_avalon_onchip_memory2
#define FFT_YN_IMAG_COMPONENT_NAME fft_yn_imag
#define FFT_YN_IMAG_BASE 0x19000
#define FFT_YN_IMAG_SPAN 4096
#define FFT_YN_IMAG_END 0x19fff

/*
 * Macros for device 'fft_xn_re', class 'altera_avalon_onchip_memory2'
 * The macros are prefixed with 'FFT_XN_RE_'.
 */
#define FFT_XN_RE_COMPONENT_TYPE altera_avalon_onchip_memory2
#define FFT_XN_RE_COMPONENT_NAME fft_xn_re
#define FFT_XN_RE_BASE 0x1a000
#define FFT_XN_RE_SPAN 4096
#define FFT_XN_RE_END 0x1afff

/*
 * Macros for device 'fft_xn_imag', class 'altera_avalon_onchip_memory2'
 * The macros are prefixed with 'FFT_XN_IMAG_'.
 */
#define FFT_XN_IMAG_COMPONENT_TYPE altera_avalon_onchip_memory2
#define FFT_XN_IMAG_COMPONENT_NAME fft_xn_imag
#define FFT_XN_IMAG_BASE 0x1b000
#define FFT_XN_IMAG_SPAN 4096
#define FFT_XN_IMAG_END 0x1bfff

/*
 * Macros for device 'adc_buf', class 'altera_avalon_onchip_memory2'
 * The macros are prefixed with 'ADC_BUF_'.
 */
#define ADC_BUF_COMPONENT_TYPE altera_avalon_onchip_memory2
#define ADC_BUF_COMPONENT_NAME adc_buf
#define ADC_BUF_BASE 0x20000
#define ADC_BUF_SPAN 131072
#define ADC_BUF_END 0x3ffff

/*
 * Macros for device 'fft_bfp_exponent', class 'altera_avalon_pio'
 * The macros are prefixed with 'FFT_BFP_EXPONENT_'.
 */
#define FFT_BFP_EXPONENT_COMPONENT_TYPE altera_avalon_pio
#define FFT_BFP_EXPONENT_COMPONENT_NAME fft_bfp_exponent
#define FFT_BFP_EXPONENT_BASE 0x50
#define FFT_BFP_EXPONENT_SPAN 16
#define FFT_BFP_EXPONENT_END 0x5f

/*
 * Macros for device 'fft_wrapper_done', class 'altera_avalon_pio'
 * The macros are prefixed with 'FFT_WRAPPER_DONE_'.
 */
#define FFT_WRAPPER_DONE_COMPONENT_TYPE altera_avalon_pio
#define FFT_WRAPPER_DONE_COMPONENT_NAME fft_wrapper_done
#define FFT_WRAPPER_DONE_BASE 0x60
#define FFT_WRAPPER_DONE_SPAN 16
#define FFT_WRAPPER_DONE_END 0x6f

/*
 * Macros for device 'fft_inverse', class 'altera_avalon_pio'
 * The macros are prefixed with 'FFT_INVERSE_'.
 */
#define FFT_INVERSE_COMPONENT_TYPE altera_avalon_pio
#define FFT_INVERSE_COMPONENT_NAME fft_inverse
#define FFT_INVERSE_BASE 0x70
#define FFT_INVERSE_SPAN 16
#define FFT_INVERSE_END 0x7f

/*
 * Macros for device 'fft_wrapper_start', class 'altera_avalon_pio'
 * The macros are prefixed with 'FFT_WRAPPER_START_'.
 */
#define FFT_WRAPPER_START_COMPONENT_TYPE altera_avalon_pio
#define FFT_WRAPPER_START_COMPONENT_NAME fft_wrapper_start
#define FFT_WRAPPER_START_BASE 0x80
#define FFT_WRAPPER_START_SPAN 16
#define FFT_WRAPPER_START_END 0x8f

/*
 * Macros for device 'adc_start', class 'altera_avalon_pio'
 * The macros are prefixed with 'ADC_START_'.
 */
#define ADC_START_COMPONENT_TYPE altera_avalon_pio
#define ADC_START_COMPONENT_NAME adc_start
#define ADC_START_BASE 0xd0
#define ADC_START_SPAN 16
#define ADC_START_END 0xdf

/*
 * Macros for device 'adc_done', class 'altera_avalon_pio'
 * The macros are prefixed with 'ADC_DONE_'.
 */
#define ADC_DONE_COMPONENT_TYPE altera_avalon_pio
#define ADC_DONE_COMPONENT_NAME adc_done
#define ADC_DONE_BASE 0xe0
#define ADC_DONE_SPAN 16
#define ADC_DONE_END 0xef

/*
 * Macros for device 'adc_config', class 'altera_avalon_pio'
 * The macros are prefixed with 'ADC_CONFIG_'.
 */
#define ADC_CONFIG_COMPONENT_TYPE altera_avalon_pio
#define ADC_CONFIG_COMPONENT_NAME adc_config
#define ADC_CONFIG_BASE 0xf0
#define ADC_CONFIG_SPAN 16
#define ADC_CONFIG_END 0xff

/*
 * Macros for device 'adc_divisor', class 'altera_avalon_pio'
 * The macros are prefixed with 'ADC_DIVISOR_'.
 */
#define ADC_DIVISOR_COMPONENT_TYPE altera_avalon_pio
#define ADC_DIVISOR_COMPONENT_NAME adc_divisor
#define ADC_DIVISOR_BASE 0x100
#define ADC_DIVISOR_SPAN 16
#define ADC_DIVISOR_END 0x10f

/*
 * Macros for device 'adc_namostras', class 'altera_avalon_pio'
 * The macros are prefixed with 'ADC_NAMOSTRAS_'.
 */
#define ADC_NAMOSTRAS_COMPONENT_TYPE altera_avalon_pio
#define ADC_NAMOSTRAS_COMPONENT_NAME adc_namostras
#define ADC_NAMOSTRAS_BASE 0x110
#define ADC_NAMOSTRAS_SPAN 16
#define ADC_NAMOSTRAS_END 0x11f

/*
 * Macros for device 'adc_contador', class 'altera_avalon_pio'
 * The macros are prefixed with 'ADC_CONTADOR_'.
 */
#define ADC_CONTADOR_COMPONENT_TYPE altera_avalon_pio
#define ADC_CONTADOR_COMPONENT_NAME adc_contador
#define ADC_CONTADOR_BASE 0x120
#define ADC_CONTADOR_SPAN 16
#define ADC_CONTADOR_END 0x12f

/*
 * Macros for device 'sysid_qsys', class 'altera_avalon_sysid_qsys'
 * The macros are prefixed with 'SYSID_QSYS_'.
 */
#define SYSID_QSYS_COMPONENT_TYPE altera_avalon_sysid_qsys
#define SYSID_QSYS_COMPONENT_NAME sysid_qsys
#define SYSID_QSYS_BASE 0x10000
#define SYSID_QSYS_SPAN 8
#define SYSID_QSYS_END 0x10007
#define SYSID_QSYS_ID 2899645186u
#define SYSID_QSYS_TIMESTAMP 1793120442u

/*
 * Macros for device 'jtag_uart', class 'altera_avalon_jtag_uart'
 * The macros are prefixed with 'JTAG_UART_'.
 */
#define JTAG_UART_COMPONENT_TYPE altera_avalon_jtag_uart
#define JTAG_UART_COMPONENT_NAME jtag_uart
#define JTAG_UART_BASE 0x20000
#define JTAG_UART_SPAN 8
#define JTAG_UART_END 0x20007

#endif /* _ALTERA_HPS_0_H_ */
