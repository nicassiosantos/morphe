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
 * Macros for device 'fir_yn', class 'altera_avalon_onchip_memory2'
 * The macros are prefixed with 'FIR_YN_'.
 */
#define FIR_YN_COMPONENT_TYPE altera_avalon_onchip_memory2
#define FIR_YN_COMPONENT_NAME fir_yn
#define FIR_YN_BASE 0x10000
#define FIR_YN_SPAN 8192
#define FIR_YN_END 0x11fff

/*
 * Macros for device 'conv1d_yn', class 'altera_avalon_onchip_memory2'
 * The macros are prefixed with 'CONV1D_YN_'.
 */
#define CONV1D_YN_COMPONENT_TYPE altera_avalon_onchip_memory2
#define CONV1D_YN_COMPONENT_NAME conv1d_yn
#define CONV1D_YN_BASE 0x12000
#define CONV1D_YN_SPAN 8192
#define CONV1D_YN_END 0x13fff

/*
 * Macros for device 'fir_hn', class 'altera_avalon_onchip_memory2'
 * The macros are prefixed with 'FIR_HN_'.
 */
#define FIR_HN_COMPONENT_TYPE altera_avalon_onchip_memory2
#define FIR_HN_COMPONENT_NAME fir_hn
#define FIR_HN_BASE 0x14000
#define FIR_HN_SPAN 4096
#define FIR_HN_END 0x14fff

/*
 * Macros for device 'fir_xn', class 'altera_avalon_onchip_memory2'
 * The macros are prefixed with 'FIR_XN_'.
 */
#define FIR_XN_COMPONENT_TYPE altera_avalon_onchip_memory2
#define FIR_XN_COMPONENT_NAME fir_xn
#define FIR_XN_BASE 0x15000
#define FIR_XN_SPAN 4096
#define FIR_XN_END 0x15fff

/*
 * Macros for device 'conv1d_hn', class 'altera_avalon_onchip_memory2'
 * The macros are prefixed with 'CONV1D_HN_'.
 */
#define CONV1D_HN_COMPONENT_TYPE altera_avalon_onchip_memory2
#define CONV1D_HN_COMPONENT_NAME conv1d_hn
#define CONV1D_HN_BASE 0x16000
#define CONV1D_HN_SPAN 4096
#define CONV1D_HN_END 0x16fff

/*
 * Macros for device 'conv1d_xn', class 'altera_avalon_onchip_memory2'
 * The macros are prefixed with 'CONV1D_XN_'.
 */
#define CONV1D_XN_COMPONENT_TYPE altera_avalon_onchip_memory2
#define CONV1D_XN_COMPONENT_NAME conv1d_xn
#define CONV1D_XN_BASE 0x17000
#define CONV1D_XN_SPAN 4096
#define CONV1D_XN_END 0x17fff

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
 * Macros for device 'fir_error', class 'altera_avalon_pio'
 * The macros are prefixed with 'FIR_ERROR_'.
 */
#define FIR_ERROR_COMPONENT_TYPE altera_avalon_pio
#define FIR_ERROR_COMPONENT_NAME fir_error
#define FIR_ERROR_BASE 0x0
#define FIR_ERROR_SPAN 16
#define FIR_ERROR_END 0xf

/*
 * Macros for device 'fir_done', class 'altera_avalon_pio'
 * The macros are prefixed with 'FIR_DONE_'.
 */
#define FIR_DONE_COMPONENT_TYPE altera_avalon_pio
#define FIR_DONE_COMPONENT_NAME fir_done
#define FIR_DONE_BASE 0x10
#define FIR_DONE_SPAN 16
#define FIR_DONE_END 0x1f

/*
 * Macros for device 'fir_start', class 'altera_avalon_pio'
 * The macros are prefixed with 'FIR_START_'.
 */
#define FIR_START_COMPONENT_TYPE altera_avalon_pio
#define FIR_START_COMPONENT_NAME fir_start
#define FIR_START_BASE 0x20
#define FIR_START_SPAN 16
#define FIR_START_END 0x2f

/*
 * Macros for device 'conv1d_done', class 'altera_avalon_pio'
 * The macros are prefixed with 'CONV1D_DONE_'.
 */
#define CONV1D_DONE_COMPONENT_TYPE altera_avalon_pio
#define CONV1D_DONE_COMPONENT_NAME conv1d_done
#define CONV1D_DONE_BASE 0x30
#define CONV1D_DONE_SPAN 16
#define CONV1D_DONE_END 0x3f

/*
 * Macros for device 'conv1d_start', class 'altera_avalon_pio'
 * The macros are prefixed with 'CONV1D_START_'.
 */
#define CONV1D_START_COMPONENT_TYPE altera_avalon_pio
#define CONV1D_START_COMPONENT_NAME conv1d_start
#define CONV1D_START_BASE 0x40
#define CONV1D_START_SPAN 16
#define CONV1D_START_END 0x4f

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
 * Macros for device 'sysid_qsys', class 'altera_avalon_sysid_qsys'
 * The macros are prefixed with 'SYSID_QSYS_'.
 */
#define SYSID_QSYS_COMPONENT_TYPE altera_avalon_sysid_qsys
#define SYSID_QSYS_COMPONENT_NAME sysid_qsys
#define SYSID_QSYS_BASE 0x10000
#define SYSID_QSYS_SPAN 8
#define SYSID_QSYS_END 0x10007

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
