
module soc_system (
	clk_clk,
	conv1d_done_export,
	conv1d_hn_address,
	conv1d_hn_clken,
	conv1d_hn_chipselect,
	conv1d_hn_write,
	conv1d_hn_readdata,
	conv1d_hn_writedata,
	conv1d_hn_byteenable,
	conv1d_start_export,
	conv1d_xn_address,
	conv1d_xn_clken,
	conv1d_xn_chipselect,
	conv1d_xn_write,
	conv1d_xn_readdata,
	conv1d_xn_writedata,
	conv1d_xn_byteenable,
	conv1d_yn_address,
	conv1d_yn_clken,
	conv1d_yn_chipselect,
	conv1d_yn_write,
	conv1d_yn_readdata,
	conv1d_yn_writedata,
	conv1d_yn_byteenable,
	fft_bfp_exponent_export,
	fft_inverse_export,
	fft_wrapper_done_export,
	fft_wrapper_start_export,
	fft_xn_imag_address,
	fft_xn_imag_clken,
	fft_xn_imag_chipselect,
	fft_xn_imag_write,
	fft_xn_imag_readdata,
	fft_xn_imag_writedata,
	fft_xn_imag_byteenable,
	fft_xn_re_address,
	fft_xn_re_clken,
	fft_xn_re_chipselect,
	fft_xn_re_write,
	fft_xn_re_readdata,
	fft_xn_re_writedata,
	fft_xn_re_byteenable,
	fft_yn_imag_address,
	fft_yn_imag_clken,
	fft_yn_imag_chipselect,
	fft_yn_imag_write,
	fft_yn_imag_readdata,
	fft_yn_imag_writedata,
	fft_yn_imag_byteenable,
	fft_yn_re_address,
	fft_yn_re_clken,
	fft_yn_re_chipselect,
	fft_yn_re_write,
	fft_yn_re_readdata,
	fft_yn_re_writedata,
	fft_yn_re_byteenable,
	fir_done_export,
	fir_error_export,
	fir_start_export,
	fir_xn_address,
	fir_xn_clken,
	fir_xn_chipselect,
	fir_xn_write,
	fir_xn_readdata,
	fir_xn_writedata,
	fir_xn_byteenable,
	fir_yn_address,
	fir_yn_clken,
	fir_yn_chipselect,
	fir_yn_write,
	fir_yn_readdata,
	fir_yn_writedata,
	fir_yn_byteenable,
	hps_0_f2h_cold_reset_req_reset_n,
	hps_0_f2h_debug_reset_req_reset_n,
	hps_0_f2h_stm_hw_events_stm_hwevents,
	hps_0_f2h_warm_reset_req_reset_n,
	hps_0_h2f_reset_reset_n,
	hps_0_hps_io_hps_io_emac1_inst_TX_CLK,
	hps_0_hps_io_hps_io_emac1_inst_TXD0,
	hps_0_hps_io_hps_io_emac1_inst_TXD1,
	hps_0_hps_io_hps_io_emac1_inst_TXD2,
	hps_0_hps_io_hps_io_emac1_inst_TXD3,
	hps_0_hps_io_hps_io_emac1_inst_RXD0,
	hps_0_hps_io_hps_io_emac1_inst_MDIO,
	hps_0_hps_io_hps_io_emac1_inst_MDC,
	hps_0_hps_io_hps_io_emac1_inst_RX_CTL,
	hps_0_hps_io_hps_io_emac1_inst_TX_CTL,
	hps_0_hps_io_hps_io_emac1_inst_RX_CLK,
	hps_0_hps_io_hps_io_emac1_inst_RXD1,
	hps_0_hps_io_hps_io_emac1_inst_RXD2,
	hps_0_hps_io_hps_io_emac1_inst_RXD3,
	hps_0_hps_io_hps_io_qspi_inst_IO0,
	hps_0_hps_io_hps_io_qspi_inst_IO1,
	hps_0_hps_io_hps_io_qspi_inst_IO2,
	hps_0_hps_io_hps_io_qspi_inst_IO3,
	hps_0_hps_io_hps_io_qspi_inst_SS0,
	hps_0_hps_io_hps_io_qspi_inst_CLK,
	hps_0_hps_io_hps_io_sdio_inst_CMD,
	hps_0_hps_io_hps_io_sdio_inst_D0,
	hps_0_hps_io_hps_io_sdio_inst_D1,
	hps_0_hps_io_hps_io_sdio_inst_CLK,
	hps_0_hps_io_hps_io_sdio_inst_D2,
	hps_0_hps_io_hps_io_sdio_inst_D3,
	hps_0_hps_io_hps_io_usb1_inst_D0,
	hps_0_hps_io_hps_io_usb1_inst_D1,
	hps_0_hps_io_hps_io_usb1_inst_D2,
	hps_0_hps_io_hps_io_usb1_inst_D3,
	hps_0_hps_io_hps_io_usb1_inst_D4,
	hps_0_hps_io_hps_io_usb1_inst_D5,
	hps_0_hps_io_hps_io_usb1_inst_D6,
	hps_0_hps_io_hps_io_usb1_inst_D7,
	hps_0_hps_io_hps_io_usb1_inst_CLK,
	hps_0_hps_io_hps_io_usb1_inst_STP,
	hps_0_hps_io_hps_io_usb1_inst_DIR,
	hps_0_hps_io_hps_io_usb1_inst_NXT,
	hps_0_hps_io_hps_io_spim1_inst_CLK,
	hps_0_hps_io_hps_io_spim1_inst_MOSI,
	hps_0_hps_io_hps_io_spim1_inst_MISO,
	hps_0_hps_io_hps_io_spim1_inst_SS0,
	hps_0_hps_io_hps_io_uart0_inst_RX,
	hps_0_hps_io_hps_io_uart0_inst_TX,
	hps_0_hps_io_hps_io_i2c0_inst_SDA,
	hps_0_hps_io_hps_io_i2c0_inst_SCL,
	hps_0_hps_io_hps_io_i2c1_inst_SDA,
	hps_0_hps_io_hps_io_i2c1_inst_SCL,
	hps_0_hps_io_hps_io_gpio_inst_GPIO09,
	hps_0_hps_io_hps_io_gpio_inst_GPIO35,
	hps_0_hps_io_hps_io_gpio_inst_GPIO40,
	hps_0_hps_io_hps_io_gpio_inst_GPIO48,
	hps_0_hps_io_hps_io_gpio_inst_GPIO53,
	hps_0_hps_io_hps_io_gpio_inst_GPIO54,
	hps_0_hps_io_hps_io_gpio_inst_GPIO61,
	memory_mem_a,
	memory_mem_ba,
	memory_mem_ck,
	memory_mem_ck_n,
	memory_mem_cke,
	memory_mem_cs_n,
	memory_mem_ras_n,
	memory_mem_cas_n,
	memory_mem_we_n,
	memory_mem_reset_n,
	memory_mem_dq,
	memory_mem_dqs,
	memory_mem_dqs_n,
	memory_mem_odt,
	memory_mem_dm,
	memory_oct_rzqin,
	reset_reset_n,
	fir_hn_address,
	fir_hn_clken,
	fir_hn_chipselect,
	fir_hn_write,
	fir_hn_readdata,
	fir_hn_writedata,
	fir_hn_byteenable);	

	input		clk_clk;
	input		conv1d_done_export;
	input	[6:0]	conv1d_hn_address;
	input		conv1d_hn_clken;
	input		conv1d_hn_chipselect;
	input		conv1d_hn_write;
	output	[31:0]	conv1d_hn_readdata;
	input	[31:0]	conv1d_hn_writedata;
	input	[3:0]	conv1d_hn_byteenable;
	output		conv1d_start_export;
	input	[6:0]	conv1d_xn_address;
	input		conv1d_xn_clken;
	input		conv1d_xn_chipselect;
	input		conv1d_xn_write;
	output	[31:0]	conv1d_xn_readdata;
	input	[31:0]	conv1d_xn_writedata;
	input	[3:0]	conv1d_xn_byteenable;
	input	[7:0]	conv1d_yn_address;
	input		conv1d_yn_clken;
	input		conv1d_yn_chipselect;
	input		conv1d_yn_write;
	output	[31:0]	conv1d_yn_readdata;
	input	[31:0]	conv1d_yn_writedata;
	input	[3:0]	conv1d_yn_byteenable;
	input	[5:0]	fft_bfp_exponent_export;
	output		fft_inverse_export;
	input		fft_wrapper_done_export;
	output		fft_wrapper_start_export;
	input	[9:0]	fft_xn_imag_address;
	input		fft_xn_imag_clken;
	input		fft_xn_imag_chipselect;
	input		fft_xn_imag_write;
	output	[31:0]	fft_xn_imag_readdata;
	input	[31:0]	fft_xn_imag_writedata;
	input	[3:0]	fft_xn_imag_byteenable;
	input	[9:0]	fft_xn_re_address;
	input		fft_xn_re_clken;
	input		fft_xn_re_chipselect;
	input		fft_xn_re_write;
	output	[31:0]	fft_xn_re_readdata;
	input	[31:0]	fft_xn_re_writedata;
	input	[3:0]	fft_xn_re_byteenable;
	input	[9:0]	fft_yn_imag_address;
	input		fft_yn_imag_clken;
	input		fft_yn_imag_chipselect;
	input		fft_yn_imag_write;
	output	[31:0]	fft_yn_imag_readdata;
	input	[31:0]	fft_yn_imag_writedata;
	input	[3:0]	fft_yn_imag_byteenable;
	input	[9:0]	fft_yn_re_address;
	input		fft_yn_re_clken;
	input		fft_yn_re_chipselect;
	input		fft_yn_re_write;
	output	[31:0]	fft_yn_re_readdata;
	input	[31:0]	fft_yn_re_writedata;
	input	[3:0]	fft_yn_re_byteenable;
	input		fir_done_export;
	input		fir_error_export;
	output		fir_start_export;
	input	[6:0]	fir_xn_address;
	input		fir_xn_clken;
	input		fir_xn_chipselect;
	input		fir_xn_write;
	output	[31:0]	fir_xn_readdata;
	input	[31:0]	fir_xn_writedata;
	input	[3:0]	fir_xn_byteenable;
	input	[6:0]	fir_yn_address;
	input		fir_yn_clken;
	input		fir_yn_chipselect;
	input		fir_yn_write;
	output	[31:0]	fir_yn_readdata;
	input	[31:0]	fir_yn_writedata;
	input	[3:0]	fir_yn_byteenable;
	input		hps_0_f2h_cold_reset_req_reset_n;
	input		hps_0_f2h_debug_reset_req_reset_n;
	input	[27:0]	hps_0_f2h_stm_hw_events_stm_hwevents;
	input		hps_0_f2h_warm_reset_req_reset_n;
	output		hps_0_h2f_reset_reset_n;
	output		hps_0_hps_io_hps_io_emac1_inst_TX_CLK;
	output		hps_0_hps_io_hps_io_emac1_inst_TXD0;
	output		hps_0_hps_io_hps_io_emac1_inst_TXD1;
	output		hps_0_hps_io_hps_io_emac1_inst_TXD2;
	output		hps_0_hps_io_hps_io_emac1_inst_TXD3;
	input		hps_0_hps_io_hps_io_emac1_inst_RXD0;
	inout		hps_0_hps_io_hps_io_emac1_inst_MDIO;
	output		hps_0_hps_io_hps_io_emac1_inst_MDC;
	input		hps_0_hps_io_hps_io_emac1_inst_RX_CTL;
	output		hps_0_hps_io_hps_io_emac1_inst_TX_CTL;
	input		hps_0_hps_io_hps_io_emac1_inst_RX_CLK;
	input		hps_0_hps_io_hps_io_emac1_inst_RXD1;
	input		hps_0_hps_io_hps_io_emac1_inst_RXD2;
	input		hps_0_hps_io_hps_io_emac1_inst_RXD3;
	inout		hps_0_hps_io_hps_io_qspi_inst_IO0;
	inout		hps_0_hps_io_hps_io_qspi_inst_IO1;
	inout		hps_0_hps_io_hps_io_qspi_inst_IO2;
	inout		hps_0_hps_io_hps_io_qspi_inst_IO3;
	output		hps_0_hps_io_hps_io_qspi_inst_SS0;
	output		hps_0_hps_io_hps_io_qspi_inst_CLK;
	inout		hps_0_hps_io_hps_io_sdio_inst_CMD;
	inout		hps_0_hps_io_hps_io_sdio_inst_D0;
	inout		hps_0_hps_io_hps_io_sdio_inst_D1;
	output		hps_0_hps_io_hps_io_sdio_inst_CLK;
	inout		hps_0_hps_io_hps_io_sdio_inst_D2;
	inout		hps_0_hps_io_hps_io_sdio_inst_D3;
	inout		hps_0_hps_io_hps_io_usb1_inst_D0;
	inout		hps_0_hps_io_hps_io_usb1_inst_D1;
	inout		hps_0_hps_io_hps_io_usb1_inst_D2;
	inout		hps_0_hps_io_hps_io_usb1_inst_D3;
	inout		hps_0_hps_io_hps_io_usb1_inst_D4;
	inout		hps_0_hps_io_hps_io_usb1_inst_D5;
	inout		hps_0_hps_io_hps_io_usb1_inst_D6;
	inout		hps_0_hps_io_hps_io_usb1_inst_D7;
	input		hps_0_hps_io_hps_io_usb1_inst_CLK;
	output		hps_0_hps_io_hps_io_usb1_inst_STP;
	input		hps_0_hps_io_hps_io_usb1_inst_DIR;
	input		hps_0_hps_io_hps_io_usb1_inst_NXT;
	output		hps_0_hps_io_hps_io_spim1_inst_CLK;
	output		hps_0_hps_io_hps_io_spim1_inst_MOSI;
	input		hps_0_hps_io_hps_io_spim1_inst_MISO;
	output		hps_0_hps_io_hps_io_spim1_inst_SS0;
	input		hps_0_hps_io_hps_io_uart0_inst_RX;
	output		hps_0_hps_io_hps_io_uart0_inst_TX;
	inout		hps_0_hps_io_hps_io_i2c0_inst_SDA;
	inout		hps_0_hps_io_hps_io_i2c0_inst_SCL;
	inout		hps_0_hps_io_hps_io_i2c1_inst_SDA;
	inout		hps_0_hps_io_hps_io_i2c1_inst_SCL;
	inout		hps_0_hps_io_hps_io_gpio_inst_GPIO09;
	inout		hps_0_hps_io_hps_io_gpio_inst_GPIO35;
	inout		hps_0_hps_io_hps_io_gpio_inst_GPIO40;
	inout		hps_0_hps_io_hps_io_gpio_inst_GPIO48;
	inout		hps_0_hps_io_hps_io_gpio_inst_GPIO53;
	inout		hps_0_hps_io_hps_io_gpio_inst_GPIO54;
	inout		hps_0_hps_io_hps_io_gpio_inst_GPIO61;
	output	[14:0]	memory_mem_a;
	output	[2:0]	memory_mem_ba;
	output		memory_mem_ck;
	output		memory_mem_ck_n;
	output		memory_mem_cke;
	output		memory_mem_cs_n;
	output		memory_mem_ras_n;
	output		memory_mem_cas_n;
	output		memory_mem_we_n;
	output		memory_mem_reset_n;
	inout	[31:0]	memory_mem_dq;
	inout	[3:0]	memory_mem_dqs;
	inout	[3:0]	memory_mem_dqs_n;
	output		memory_mem_odt;
	output	[3:0]	memory_mem_dm;
	input		memory_oct_rzqin;
	input		reset_reset_n;
	input	[6:0]	fir_hn_address;
	input		fir_hn_clken;
	input		fir_hn_chipselect;
	input		fir_hn_write;
	output	[31:0]	fir_hn_readdata;
	input	[31:0]	fir_hn_writedata;
	input	[3:0]	fir_hn_byteenable;
endmodule
