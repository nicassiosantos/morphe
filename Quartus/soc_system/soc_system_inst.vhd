	component soc_system is
		port (
			clk_clk                               : in    std_logic                     := 'X';             -- clk
			conv1d_done_export                    : in    std_logic                     := 'X';             -- export
			conv1d_hn_address                     : in    std_logic_vector(6 downto 0)  := (others => 'X'); -- address
			conv1d_hn_clken                       : in    std_logic                     := 'X';             -- clken
			conv1d_hn_chipselect                  : in    std_logic                     := 'X';             -- chipselect
			conv1d_hn_write                       : in    std_logic                     := 'X';             -- write
			conv1d_hn_readdata                    : out   std_logic_vector(31 downto 0);                    -- readdata
			conv1d_hn_writedata                   : in    std_logic_vector(31 downto 0) := (others => 'X'); -- writedata
			conv1d_hn_byteenable                  : in    std_logic_vector(3 downto 0)  := (others => 'X'); -- byteenable
			conv1d_start_export                   : out   std_logic;                                        -- export
			conv1d_xn_address                     : in    std_logic_vector(6 downto 0)  := (others => 'X'); -- address
			conv1d_xn_clken                       : in    std_logic                     := 'X';             -- clken
			conv1d_xn_chipselect                  : in    std_logic                     := 'X';             -- chipselect
			conv1d_xn_write                       : in    std_logic                     := 'X';             -- write
			conv1d_xn_readdata                    : out   std_logic_vector(31 downto 0);                    -- readdata
			conv1d_xn_writedata                   : in    std_logic_vector(31 downto 0) := (others => 'X'); -- writedata
			conv1d_xn_byteenable                  : in    std_logic_vector(3 downto 0)  := (others => 'X'); -- byteenable
			conv1d_yn_address                     : in    std_logic_vector(7 downto 0)  := (others => 'X'); -- address
			conv1d_yn_clken                       : in    std_logic                     := 'X';             -- clken
			conv1d_yn_chipselect                  : in    std_logic                     := 'X';             -- chipselect
			conv1d_yn_write                       : in    std_logic                     := 'X';             -- write
			conv1d_yn_readdata                    : out   std_logic_vector(31 downto 0);                    -- readdata
			conv1d_yn_writedata                   : in    std_logic_vector(31 downto 0) := (others => 'X'); -- writedata
			conv1d_yn_byteenable                  : in    std_logic_vector(3 downto 0)  := (others => 'X'); -- byteenable
			fft_bfp_exponent_export               : in    std_logic_vector(5 downto 0)  := (others => 'X'); -- export
			fft_inverse_export                    : out   std_logic;                                        -- export
			fft_wrapper_done_export               : in    std_logic                     := 'X';             -- export
			fft_wrapper_start_export              : out   std_logic;                                        -- export
			fft_xn_imag_address                   : in    std_logic_vector(9 downto 0)  := (others => 'X'); -- address
			fft_xn_imag_clken                     : in    std_logic                     := 'X';             -- clken
			fft_xn_imag_chipselect                : in    std_logic                     := 'X';             -- chipselect
			fft_xn_imag_write                     : in    std_logic                     := 'X';             -- write
			fft_xn_imag_readdata                  : out   std_logic_vector(31 downto 0);                    -- readdata
			fft_xn_imag_writedata                 : in    std_logic_vector(31 downto 0) := (others => 'X'); -- writedata
			fft_xn_imag_byteenable                : in    std_logic_vector(3 downto 0)  := (others => 'X'); -- byteenable
			fft_xn_re_address                     : in    std_logic_vector(9 downto 0)  := (others => 'X'); -- address
			fft_xn_re_clken                       : in    std_logic                     := 'X';             -- clken
			fft_xn_re_chipselect                  : in    std_logic                     := 'X';             -- chipselect
			fft_xn_re_write                       : in    std_logic                     := 'X';             -- write
			fft_xn_re_readdata                    : out   std_logic_vector(31 downto 0);                    -- readdata
			fft_xn_re_writedata                   : in    std_logic_vector(31 downto 0) := (others => 'X'); -- writedata
			fft_xn_re_byteenable                  : in    std_logic_vector(3 downto 0)  := (others => 'X'); -- byteenable
			fft_yn_imag_address                   : in    std_logic_vector(9 downto 0)  := (others => 'X'); -- address
			fft_yn_imag_clken                     : in    std_logic                     := 'X';             -- clken
			fft_yn_imag_chipselect                : in    std_logic                     := 'X';             -- chipselect
			fft_yn_imag_write                     : in    std_logic                     := 'X';             -- write
			fft_yn_imag_readdata                  : out   std_logic_vector(31 downto 0);                    -- readdata
			fft_yn_imag_writedata                 : in    std_logic_vector(31 downto 0) := (others => 'X'); -- writedata
			fft_yn_imag_byteenable                : in    std_logic_vector(3 downto 0)  := (others => 'X'); -- byteenable
			fft_yn_re_address                     : in    std_logic_vector(9 downto 0)  := (others => 'X'); -- address
			fft_yn_re_clken                       : in    std_logic                     := 'X';             -- clken
			fft_yn_re_chipselect                  : in    std_logic                     := 'X';             -- chipselect
			fft_yn_re_write                       : in    std_logic                     := 'X';             -- write
			fft_yn_re_readdata                    : out   std_logic_vector(31 downto 0);                    -- readdata
			fft_yn_re_writedata                   : in    std_logic_vector(31 downto 0) := (others => 'X'); -- writedata
			fft_yn_re_byteenable                  : in    std_logic_vector(3 downto 0)  := (others => 'X'); -- byteenable
			fir_done_export                       : in    std_logic                     := 'X';             -- export
			fir_error_export                      : in    std_logic                     := 'X';             -- export
			fir_start_export                      : out   std_logic;                                        -- export
			fir_xn_address                        : in    std_logic_vector(6 downto 0)  := (others => 'X'); -- address
			fir_xn_clken                          : in    std_logic                     := 'X';             -- clken
			fir_xn_chipselect                     : in    std_logic                     := 'X';             -- chipselect
			fir_xn_write                          : in    std_logic                     := 'X';             -- write
			fir_xn_readdata                       : out   std_logic_vector(31 downto 0);                    -- readdata
			fir_xn_writedata                      : in    std_logic_vector(31 downto 0) := (others => 'X'); -- writedata
			fir_xn_byteenable                     : in    std_logic_vector(3 downto 0)  := (others => 'X'); -- byteenable
			fir_yn_address                        : in    std_logic_vector(6 downto 0)  := (others => 'X'); -- address
			fir_yn_clken                          : in    std_logic                     := 'X';             -- clken
			fir_yn_chipselect                     : in    std_logic                     := 'X';             -- chipselect
			fir_yn_write                          : in    std_logic                     := 'X';             -- write
			fir_yn_readdata                       : out   std_logic_vector(31 downto 0);                    -- readdata
			fir_yn_writedata                      : in    std_logic_vector(31 downto 0) := (others => 'X'); -- writedata
			fir_yn_byteenable                     : in    std_logic_vector(3 downto 0)  := (others => 'X'); -- byteenable
			hps_0_f2h_cold_reset_req_reset_n      : in    std_logic                     := 'X';             -- reset_n
			hps_0_f2h_debug_reset_req_reset_n     : in    std_logic                     := 'X';             -- reset_n
			hps_0_f2h_stm_hw_events_stm_hwevents  : in    std_logic_vector(27 downto 0) := (others => 'X'); -- stm_hwevents
			hps_0_f2h_warm_reset_req_reset_n      : in    std_logic                     := 'X';             -- reset_n
			hps_0_h2f_reset_reset_n               : out   std_logic;                                        -- reset_n
			hps_0_hps_io_hps_io_emac1_inst_TX_CLK : out   std_logic;                                        -- hps_io_emac1_inst_TX_CLK
			hps_0_hps_io_hps_io_emac1_inst_TXD0   : out   std_logic;                                        -- hps_io_emac1_inst_TXD0
			hps_0_hps_io_hps_io_emac1_inst_TXD1   : out   std_logic;                                        -- hps_io_emac1_inst_TXD1
			hps_0_hps_io_hps_io_emac1_inst_TXD2   : out   std_logic;                                        -- hps_io_emac1_inst_TXD2
			hps_0_hps_io_hps_io_emac1_inst_TXD3   : out   std_logic;                                        -- hps_io_emac1_inst_TXD3
			hps_0_hps_io_hps_io_emac1_inst_RXD0   : in    std_logic                     := 'X';             -- hps_io_emac1_inst_RXD0
			hps_0_hps_io_hps_io_emac1_inst_MDIO   : inout std_logic                     := 'X';             -- hps_io_emac1_inst_MDIO
			hps_0_hps_io_hps_io_emac1_inst_MDC    : out   std_logic;                                        -- hps_io_emac1_inst_MDC
			hps_0_hps_io_hps_io_emac1_inst_RX_CTL : in    std_logic                     := 'X';             -- hps_io_emac1_inst_RX_CTL
			hps_0_hps_io_hps_io_emac1_inst_TX_CTL : out   std_logic;                                        -- hps_io_emac1_inst_TX_CTL
			hps_0_hps_io_hps_io_emac1_inst_RX_CLK : in    std_logic                     := 'X';             -- hps_io_emac1_inst_RX_CLK
			hps_0_hps_io_hps_io_emac1_inst_RXD1   : in    std_logic                     := 'X';             -- hps_io_emac1_inst_RXD1
			hps_0_hps_io_hps_io_emac1_inst_RXD2   : in    std_logic                     := 'X';             -- hps_io_emac1_inst_RXD2
			hps_0_hps_io_hps_io_emac1_inst_RXD3   : in    std_logic                     := 'X';             -- hps_io_emac1_inst_RXD3
			hps_0_hps_io_hps_io_qspi_inst_IO0     : inout std_logic                     := 'X';             -- hps_io_qspi_inst_IO0
			hps_0_hps_io_hps_io_qspi_inst_IO1     : inout std_logic                     := 'X';             -- hps_io_qspi_inst_IO1
			hps_0_hps_io_hps_io_qspi_inst_IO2     : inout std_logic                     := 'X';             -- hps_io_qspi_inst_IO2
			hps_0_hps_io_hps_io_qspi_inst_IO3     : inout std_logic                     := 'X';             -- hps_io_qspi_inst_IO3
			hps_0_hps_io_hps_io_qspi_inst_SS0     : out   std_logic;                                        -- hps_io_qspi_inst_SS0
			hps_0_hps_io_hps_io_qspi_inst_CLK     : out   std_logic;                                        -- hps_io_qspi_inst_CLK
			hps_0_hps_io_hps_io_sdio_inst_CMD     : inout std_logic                     := 'X';             -- hps_io_sdio_inst_CMD
			hps_0_hps_io_hps_io_sdio_inst_D0      : inout std_logic                     := 'X';             -- hps_io_sdio_inst_D0
			hps_0_hps_io_hps_io_sdio_inst_D1      : inout std_logic                     := 'X';             -- hps_io_sdio_inst_D1
			hps_0_hps_io_hps_io_sdio_inst_CLK     : out   std_logic;                                        -- hps_io_sdio_inst_CLK
			hps_0_hps_io_hps_io_sdio_inst_D2      : inout std_logic                     := 'X';             -- hps_io_sdio_inst_D2
			hps_0_hps_io_hps_io_sdio_inst_D3      : inout std_logic                     := 'X';             -- hps_io_sdio_inst_D3
			hps_0_hps_io_hps_io_usb1_inst_D0      : inout std_logic                     := 'X';             -- hps_io_usb1_inst_D0
			hps_0_hps_io_hps_io_usb1_inst_D1      : inout std_logic                     := 'X';             -- hps_io_usb1_inst_D1
			hps_0_hps_io_hps_io_usb1_inst_D2      : inout std_logic                     := 'X';             -- hps_io_usb1_inst_D2
			hps_0_hps_io_hps_io_usb1_inst_D3      : inout std_logic                     := 'X';             -- hps_io_usb1_inst_D3
			hps_0_hps_io_hps_io_usb1_inst_D4      : inout std_logic                     := 'X';             -- hps_io_usb1_inst_D4
			hps_0_hps_io_hps_io_usb1_inst_D5      : inout std_logic                     := 'X';             -- hps_io_usb1_inst_D5
			hps_0_hps_io_hps_io_usb1_inst_D6      : inout std_logic                     := 'X';             -- hps_io_usb1_inst_D6
			hps_0_hps_io_hps_io_usb1_inst_D7      : inout std_logic                     := 'X';             -- hps_io_usb1_inst_D7
			hps_0_hps_io_hps_io_usb1_inst_CLK     : in    std_logic                     := 'X';             -- hps_io_usb1_inst_CLK
			hps_0_hps_io_hps_io_usb1_inst_STP     : out   std_logic;                                        -- hps_io_usb1_inst_STP
			hps_0_hps_io_hps_io_usb1_inst_DIR     : in    std_logic                     := 'X';             -- hps_io_usb1_inst_DIR
			hps_0_hps_io_hps_io_usb1_inst_NXT     : in    std_logic                     := 'X';             -- hps_io_usb1_inst_NXT
			hps_0_hps_io_hps_io_spim1_inst_CLK    : out   std_logic;                                        -- hps_io_spim1_inst_CLK
			hps_0_hps_io_hps_io_spim1_inst_MOSI   : out   std_logic;                                        -- hps_io_spim1_inst_MOSI
			hps_0_hps_io_hps_io_spim1_inst_MISO   : in    std_logic                     := 'X';             -- hps_io_spim1_inst_MISO
			hps_0_hps_io_hps_io_spim1_inst_SS0    : out   std_logic;                                        -- hps_io_spim1_inst_SS0
			hps_0_hps_io_hps_io_uart0_inst_RX     : in    std_logic                     := 'X';             -- hps_io_uart0_inst_RX
			hps_0_hps_io_hps_io_uart0_inst_TX     : out   std_logic;                                        -- hps_io_uart0_inst_TX
			hps_0_hps_io_hps_io_i2c0_inst_SDA     : inout std_logic                     := 'X';             -- hps_io_i2c0_inst_SDA
			hps_0_hps_io_hps_io_i2c0_inst_SCL     : inout std_logic                     := 'X';             -- hps_io_i2c0_inst_SCL
			hps_0_hps_io_hps_io_i2c1_inst_SDA     : inout std_logic                     := 'X';             -- hps_io_i2c1_inst_SDA
			hps_0_hps_io_hps_io_i2c1_inst_SCL     : inout std_logic                     := 'X';             -- hps_io_i2c1_inst_SCL
			hps_0_hps_io_hps_io_gpio_inst_GPIO09  : inout std_logic                     := 'X';             -- hps_io_gpio_inst_GPIO09
			hps_0_hps_io_hps_io_gpio_inst_GPIO35  : inout std_logic                     := 'X';             -- hps_io_gpio_inst_GPIO35
			hps_0_hps_io_hps_io_gpio_inst_GPIO40  : inout std_logic                     := 'X';             -- hps_io_gpio_inst_GPIO40
			hps_0_hps_io_hps_io_gpio_inst_GPIO48  : inout std_logic                     := 'X';             -- hps_io_gpio_inst_GPIO48
			hps_0_hps_io_hps_io_gpio_inst_GPIO53  : inout std_logic                     := 'X';             -- hps_io_gpio_inst_GPIO53
			hps_0_hps_io_hps_io_gpio_inst_GPIO54  : inout std_logic                     := 'X';             -- hps_io_gpio_inst_GPIO54
			hps_0_hps_io_hps_io_gpio_inst_GPIO61  : inout std_logic                     := 'X';             -- hps_io_gpio_inst_GPIO61
			memory_mem_a                          : out   std_logic_vector(14 downto 0);                    -- mem_a
			memory_mem_ba                         : out   std_logic_vector(2 downto 0);                     -- mem_ba
			memory_mem_ck                         : out   std_logic;                                        -- mem_ck
			memory_mem_ck_n                       : out   std_logic;                                        -- mem_ck_n
			memory_mem_cke                        : out   std_logic;                                        -- mem_cke
			memory_mem_cs_n                       : out   std_logic;                                        -- mem_cs_n
			memory_mem_ras_n                      : out   std_logic;                                        -- mem_ras_n
			memory_mem_cas_n                      : out   std_logic;                                        -- mem_cas_n
			memory_mem_we_n                       : out   std_logic;                                        -- mem_we_n
			memory_mem_reset_n                    : out   std_logic;                                        -- mem_reset_n
			memory_mem_dq                         : inout std_logic_vector(31 downto 0) := (others => 'X'); -- mem_dq
			memory_mem_dqs                        : inout std_logic_vector(3 downto 0)  := (others => 'X'); -- mem_dqs
			memory_mem_dqs_n                      : inout std_logic_vector(3 downto 0)  := (others => 'X'); -- mem_dqs_n
			memory_mem_odt                        : out   std_logic;                                        -- mem_odt
			memory_mem_dm                         : out   std_logic_vector(3 downto 0);                     -- mem_dm
			memory_oct_rzqin                      : in    std_logic                     := 'X';             -- oct_rzqin
			reset_reset_n                         : in    std_logic                     := 'X';             -- reset_n
			fir_hn_address                        : in    std_logic_vector(6 downto 0)  := (others => 'X'); -- address
			fir_hn_clken                          : in    std_logic                     := 'X';             -- clken
			fir_hn_chipselect                     : in    std_logic                     := 'X';             -- chipselect
			fir_hn_write                          : in    std_logic                     := 'X';             -- write
			fir_hn_readdata                       : out   std_logic_vector(31 downto 0);                    -- readdata
			fir_hn_writedata                      : in    std_logic_vector(31 downto 0) := (others => 'X'); -- writedata
			fir_hn_byteenable                     : in    std_logic_vector(3 downto 0)  := (others => 'X')  -- byteenable
		);
	end component soc_system;

	u0 : component soc_system
		port map (
			clk_clk                               => CONNECTED_TO_clk_clk,                               --                       clk.clk
			conv1d_done_export                    => CONNECTED_TO_conv1d_done_export,                    --               conv1d_done.export
			conv1d_hn_address                     => CONNECTED_TO_conv1d_hn_address,                     --                 conv1d_hn.address
			conv1d_hn_clken                       => CONNECTED_TO_conv1d_hn_clken,                       --                          .clken
			conv1d_hn_chipselect                  => CONNECTED_TO_conv1d_hn_chipselect,                  --                          .chipselect
			conv1d_hn_write                       => CONNECTED_TO_conv1d_hn_write,                       --                          .write
			conv1d_hn_readdata                    => CONNECTED_TO_conv1d_hn_readdata,                    --                          .readdata
			conv1d_hn_writedata                   => CONNECTED_TO_conv1d_hn_writedata,                   --                          .writedata
			conv1d_hn_byteenable                  => CONNECTED_TO_conv1d_hn_byteenable,                  --                          .byteenable
			conv1d_start_export                   => CONNECTED_TO_conv1d_start_export,                   --              conv1d_start.export
			conv1d_xn_address                     => CONNECTED_TO_conv1d_xn_address,                     --                 conv1d_xn.address
			conv1d_xn_clken                       => CONNECTED_TO_conv1d_xn_clken,                       --                          .clken
			conv1d_xn_chipselect                  => CONNECTED_TO_conv1d_xn_chipselect,                  --                          .chipselect
			conv1d_xn_write                       => CONNECTED_TO_conv1d_xn_write,                       --                          .write
			conv1d_xn_readdata                    => CONNECTED_TO_conv1d_xn_readdata,                    --                          .readdata
			conv1d_xn_writedata                   => CONNECTED_TO_conv1d_xn_writedata,                   --                          .writedata
			conv1d_xn_byteenable                  => CONNECTED_TO_conv1d_xn_byteenable,                  --                          .byteenable
			conv1d_yn_address                     => CONNECTED_TO_conv1d_yn_address,                     --                 conv1d_yn.address
			conv1d_yn_clken                       => CONNECTED_TO_conv1d_yn_clken,                       --                          .clken
			conv1d_yn_chipselect                  => CONNECTED_TO_conv1d_yn_chipselect,                  --                          .chipselect
			conv1d_yn_write                       => CONNECTED_TO_conv1d_yn_write,                       --                          .write
			conv1d_yn_readdata                    => CONNECTED_TO_conv1d_yn_readdata,                    --                          .readdata
			conv1d_yn_writedata                   => CONNECTED_TO_conv1d_yn_writedata,                   --                          .writedata
			conv1d_yn_byteenable                  => CONNECTED_TO_conv1d_yn_byteenable,                  --                          .byteenable
			fft_bfp_exponent_export               => CONNECTED_TO_fft_bfp_exponent_export,               --          fft_bfp_exponent.export
			fft_inverse_export                    => CONNECTED_TO_fft_inverse_export,                    --               fft_inverse.export
			fft_wrapper_done_export               => CONNECTED_TO_fft_wrapper_done_export,               --          fft_wrapper_done.export
			fft_wrapper_start_export              => CONNECTED_TO_fft_wrapper_start_export,              --         fft_wrapper_start.export
			fft_xn_imag_address                   => CONNECTED_TO_fft_xn_imag_address,                   --               fft_xn_imag.address
			fft_xn_imag_clken                     => CONNECTED_TO_fft_xn_imag_clken,                     --                          .clken
			fft_xn_imag_chipselect                => CONNECTED_TO_fft_xn_imag_chipselect,                --                          .chipselect
			fft_xn_imag_write                     => CONNECTED_TO_fft_xn_imag_write,                     --                          .write
			fft_xn_imag_readdata                  => CONNECTED_TO_fft_xn_imag_readdata,                  --                          .readdata
			fft_xn_imag_writedata                 => CONNECTED_TO_fft_xn_imag_writedata,                 --                          .writedata
			fft_xn_imag_byteenable                => CONNECTED_TO_fft_xn_imag_byteenable,                --                          .byteenable
			fft_xn_re_address                     => CONNECTED_TO_fft_xn_re_address,                     --                 fft_xn_re.address
			fft_xn_re_clken                       => CONNECTED_TO_fft_xn_re_clken,                       --                          .clken
			fft_xn_re_chipselect                  => CONNECTED_TO_fft_xn_re_chipselect,                  --                          .chipselect
			fft_xn_re_write                       => CONNECTED_TO_fft_xn_re_write,                       --                          .write
			fft_xn_re_readdata                    => CONNECTED_TO_fft_xn_re_readdata,                    --                          .readdata
			fft_xn_re_writedata                   => CONNECTED_TO_fft_xn_re_writedata,                   --                          .writedata
			fft_xn_re_byteenable                  => CONNECTED_TO_fft_xn_re_byteenable,                  --                          .byteenable
			fft_yn_imag_address                   => CONNECTED_TO_fft_yn_imag_address,                   --               fft_yn_imag.address
			fft_yn_imag_clken                     => CONNECTED_TO_fft_yn_imag_clken,                     --                          .clken
			fft_yn_imag_chipselect                => CONNECTED_TO_fft_yn_imag_chipselect,                --                          .chipselect
			fft_yn_imag_write                     => CONNECTED_TO_fft_yn_imag_write,                     --                          .write
			fft_yn_imag_readdata                  => CONNECTED_TO_fft_yn_imag_readdata,                  --                          .readdata
			fft_yn_imag_writedata                 => CONNECTED_TO_fft_yn_imag_writedata,                 --                          .writedata
			fft_yn_imag_byteenable                => CONNECTED_TO_fft_yn_imag_byteenable,                --                          .byteenable
			fft_yn_re_address                     => CONNECTED_TO_fft_yn_re_address,                     --                 fft_yn_re.address
			fft_yn_re_clken                       => CONNECTED_TO_fft_yn_re_clken,                       --                          .clken
			fft_yn_re_chipselect                  => CONNECTED_TO_fft_yn_re_chipselect,                  --                          .chipselect
			fft_yn_re_write                       => CONNECTED_TO_fft_yn_re_write,                       --                          .write
			fft_yn_re_readdata                    => CONNECTED_TO_fft_yn_re_readdata,                    --                          .readdata
			fft_yn_re_writedata                   => CONNECTED_TO_fft_yn_re_writedata,                   --                          .writedata
			fft_yn_re_byteenable                  => CONNECTED_TO_fft_yn_re_byteenable,                  --                          .byteenable
			fir_done_export                       => CONNECTED_TO_fir_done_export,                       --                  fir_done.export
			fir_error_export                      => CONNECTED_TO_fir_error_export,                      --                 fir_error.export
			fir_start_export                      => CONNECTED_TO_fir_start_export,                      --                 fir_start.export
			fir_xn_address                        => CONNECTED_TO_fir_xn_address,                        --                    fir_xn.address
			fir_xn_clken                          => CONNECTED_TO_fir_xn_clken,                          --                          .clken
			fir_xn_chipselect                     => CONNECTED_TO_fir_xn_chipselect,                     --                          .chipselect
			fir_xn_write                          => CONNECTED_TO_fir_xn_write,                          --                          .write
			fir_xn_readdata                       => CONNECTED_TO_fir_xn_readdata,                       --                          .readdata
			fir_xn_writedata                      => CONNECTED_TO_fir_xn_writedata,                      --                          .writedata
			fir_xn_byteenable                     => CONNECTED_TO_fir_xn_byteenable,                     --                          .byteenable
			fir_yn_address                        => CONNECTED_TO_fir_yn_address,                        --                    fir_yn.address
			fir_yn_clken                          => CONNECTED_TO_fir_yn_clken,                          --                          .clken
			fir_yn_chipselect                     => CONNECTED_TO_fir_yn_chipselect,                     --                          .chipselect
			fir_yn_write                          => CONNECTED_TO_fir_yn_write,                          --                          .write
			fir_yn_readdata                       => CONNECTED_TO_fir_yn_readdata,                       --                          .readdata
			fir_yn_writedata                      => CONNECTED_TO_fir_yn_writedata,                      --                          .writedata
			fir_yn_byteenable                     => CONNECTED_TO_fir_yn_byteenable,                     --                          .byteenable
			hps_0_f2h_cold_reset_req_reset_n      => CONNECTED_TO_hps_0_f2h_cold_reset_req_reset_n,      --  hps_0_f2h_cold_reset_req.reset_n
			hps_0_f2h_debug_reset_req_reset_n     => CONNECTED_TO_hps_0_f2h_debug_reset_req_reset_n,     -- hps_0_f2h_debug_reset_req.reset_n
			hps_0_f2h_stm_hw_events_stm_hwevents  => CONNECTED_TO_hps_0_f2h_stm_hw_events_stm_hwevents,  --   hps_0_f2h_stm_hw_events.stm_hwevents
			hps_0_f2h_warm_reset_req_reset_n      => CONNECTED_TO_hps_0_f2h_warm_reset_req_reset_n,      --  hps_0_f2h_warm_reset_req.reset_n
			hps_0_h2f_reset_reset_n               => CONNECTED_TO_hps_0_h2f_reset_reset_n,               --           hps_0_h2f_reset.reset_n
			hps_0_hps_io_hps_io_emac1_inst_TX_CLK => CONNECTED_TO_hps_0_hps_io_hps_io_emac1_inst_TX_CLK, --              hps_0_hps_io.hps_io_emac1_inst_TX_CLK
			hps_0_hps_io_hps_io_emac1_inst_TXD0   => CONNECTED_TO_hps_0_hps_io_hps_io_emac1_inst_TXD0,   --                          .hps_io_emac1_inst_TXD0
			hps_0_hps_io_hps_io_emac1_inst_TXD1   => CONNECTED_TO_hps_0_hps_io_hps_io_emac1_inst_TXD1,   --                          .hps_io_emac1_inst_TXD1
			hps_0_hps_io_hps_io_emac1_inst_TXD2   => CONNECTED_TO_hps_0_hps_io_hps_io_emac1_inst_TXD2,   --                          .hps_io_emac1_inst_TXD2
			hps_0_hps_io_hps_io_emac1_inst_TXD3   => CONNECTED_TO_hps_0_hps_io_hps_io_emac1_inst_TXD3,   --                          .hps_io_emac1_inst_TXD3
			hps_0_hps_io_hps_io_emac1_inst_RXD0   => CONNECTED_TO_hps_0_hps_io_hps_io_emac1_inst_RXD0,   --                          .hps_io_emac1_inst_RXD0
			hps_0_hps_io_hps_io_emac1_inst_MDIO   => CONNECTED_TO_hps_0_hps_io_hps_io_emac1_inst_MDIO,   --                          .hps_io_emac1_inst_MDIO
			hps_0_hps_io_hps_io_emac1_inst_MDC    => CONNECTED_TO_hps_0_hps_io_hps_io_emac1_inst_MDC,    --                          .hps_io_emac1_inst_MDC
			hps_0_hps_io_hps_io_emac1_inst_RX_CTL => CONNECTED_TO_hps_0_hps_io_hps_io_emac1_inst_RX_CTL, --                          .hps_io_emac1_inst_RX_CTL
			hps_0_hps_io_hps_io_emac1_inst_TX_CTL => CONNECTED_TO_hps_0_hps_io_hps_io_emac1_inst_TX_CTL, --                          .hps_io_emac1_inst_TX_CTL
			hps_0_hps_io_hps_io_emac1_inst_RX_CLK => CONNECTED_TO_hps_0_hps_io_hps_io_emac1_inst_RX_CLK, --                          .hps_io_emac1_inst_RX_CLK
			hps_0_hps_io_hps_io_emac1_inst_RXD1   => CONNECTED_TO_hps_0_hps_io_hps_io_emac1_inst_RXD1,   --                          .hps_io_emac1_inst_RXD1
			hps_0_hps_io_hps_io_emac1_inst_RXD2   => CONNECTED_TO_hps_0_hps_io_hps_io_emac1_inst_RXD2,   --                          .hps_io_emac1_inst_RXD2
			hps_0_hps_io_hps_io_emac1_inst_RXD3   => CONNECTED_TO_hps_0_hps_io_hps_io_emac1_inst_RXD3,   --                          .hps_io_emac1_inst_RXD3
			hps_0_hps_io_hps_io_qspi_inst_IO0     => CONNECTED_TO_hps_0_hps_io_hps_io_qspi_inst_IO0,     --                          .hps_io_qspi_inst_IO0
			hps_0_hps_io_hps_io_qspi_inst_IO1     => CONNECTED_TO_hps_0_hps_io_hps_io_qspi_inst_IO1,     --                          .hps_io_qspi_inst_IO1
			hps_0_hps_io_hps_io_qspi_inst_IO2     => CONNECTED_TO_hps_0_hps_io_hps_io_qspi_inst_IO2,     --                          .hps_io_qspi_inst_IO2
			hps_0_hps_io_hps_io_qspi_inst_IO3     => CONNECTED_TO_hps_0_hps_io_hps_io_qspi_inst_IO3,     --                          .hps_io_qspi_inst_IO3
			hps_0_hps_io_hps_io_qspi_inst_SS0     => CONNECTED_TO_hps_0_hps_io_hps_io_qspi_inst_SS0,     --                          .hps_io_qspi_inst_SS0
			hps_0_hps_io_hps_io_qspi_inst_CLK     => CONNECTED_TO_hps_0_hps_io_hps_io_qspi_inst_CLK,     --                          .hps_io_qspi_inst_CLK
			hps_0_hps_io_hps_io_sdio_inst_CMD     => CONNECTED_TO_hps_0_hps_io_hps_io_sdio_inst_CMD,     --                          .hps_io_sdio_inst_CMD
			hps_0_hps_io_hps_io_sdio_inst_D0      => CONNECTED_TO_hps_0_hps_io_hps_io_sdio_inst_D0,      --                          .hps_io_sdio_inst_D0
			hps_0_hps_io_hps_io_sdio_inst_D1      => CONNECTED_TO_hps_0_hps_io_hps_io_sdio_inst_D1,      --                          .hps_io_sdio_inst_D1
			hps_0_hps_io_hps_io_sdio_inst_CLK     => CONNECTED_TO_hps_0_hps_io_hps_io_sdio_inst_CLK,     --                          .hps_io_sdio_inst_CLK
			hps_0_hps_io_hps_io_sdio_inst_D2      => CONNECTED_TO_hps_0_hps_io_hps_io_sdio_inst_D2,      --                          .hps_io_sdio_inst_D2
			hps_0_hps_io_hps_io_sdio_inst_D3      => CONNECTED_TO_hps_0_hps_io_hps_io_sdio_inst_D3,      --                          .hps_io_sdio_inst_D3
			hps_0_hps_io_hps_io_usb1_inst_D0      => CONNECTED_TO_hps_0_hps_io_hps_io_usb1_inst_D0,      --                          .hps_io_usb1_inst_D0
			hps_0_hps_io_hps_io_usb1_inst_D1      => CONNECTED_TO_hps_0_hps_io_hps_io_usb1_inst_D1,      --                          .hps_io_usb1_inst_D1
			hps_0_hps_io_hps_io_usb1_inst_D2      => CONNECTED_TO_hps_0_hps_io_hps_io_usb1_inst_D2,      --                          .hps_io_usb1_inst_D2
			hps_0_hps_io_hps_io_usb1_inst_D3      => CONNECTED_TO_hps_0_hps_io_hps_io_usb1_inst_D3,      --                          .hps_io_usb1_inst_D3
			hps_0_hps_io_hps_io_usb1_inst_D4      => CONNECTED_TO_hps_0_hps_io_hps_io_usb1_inst_D4,      --                          .hps_io_usb1_inst_D4
			hps_0_hps_io_hps_io_usb1_inst_D5      => CONNECTED_TO_hps_0_hps_io_hps_io_usb1_inst_D5,      --                          .hps_io_usb1_inst_D5
			hps_0_hps_io_hps_io_usb1_inst_D6      => CONNECTED_TO_hps_0_hps_io_hps_io_usb1_inst_D6,      --                          .hps_io_usb1_inst_D6
			hps_0_hps_io_hps_io_usb1_inst_D7      => CONNECTED_TO_hps_0_hps_io_hps_io_usb1_inst_D7,      --                          .hps_io_usb1_inst_D7
			hps_0_hps_io_hps_io_usb1_inst_CLK     => CONNECTED_TO_hps_0_hps_io_hps_io_usb1_inst_CLK,     --                          .hps_io_usb1_inst_CLK
			hps_0_hps_io_hps_io_usb1_inst_STP     => CONNECTED_TO_hps_0_hps_io_hps_io_usb1_inst_STP,     --                          .hps_io_usb1_inst_STP
			hps_0_hps_io_hps_io_usb1_inst_DIR     => CONNECTED_TO_hps_0_hps_io_hps_io_usb1_inst_DIR,     --                          .hps_io_usb1_inst_DIR
			hps_0_hps_io_hps_io_usb1_inst_NXT     => CONNECTED_TO_hps_0_hps_io_hps_io_usb1_inst_NXT,     --                          .hps_io_usb1_inst_NXT
			hps_0_hps_io_hps_io_spim1_inst_CLK    => CONNECTED_TO_hps_0_hps_io_hps_io_spim1_inst_CLK,    --                          .hps_io_spim1_inst_CLK
			hps_0_hps_io_hps_io_spim1_inst_MOSI   => CONNECTED_TO_hps_0_hps_io_hps_io_spim1_inst_MOSI,   --                          .hps_io_spim1_inst_MOSI
			hps_0_hps_io_hps_io_spim1_inst_MISO   => CONNECTED_TO_hps_0_hps_io_hps_io_spim1_inst_MISO,   --                          .hps_io_spim1_inst_MISO
			hps_0_hps_io_hps_io_spim1_inst_SS0    => CONNECTED_TO_hps_0_hps_io_hps_io_spim1_inst_SS0,    --                          .hps_io_spim1_inst_SS0
			hps_0_hps_io_hps_io_uart0_inst_RX     => CONNECTED_TO_hps_0_hps_io_hps_io_uart0_inst_RX,     --                          .hps_io_uart0_inst_RX
			hps_0_hps_io_hps_io_uart0_inst_TX     => CONNECTED_TO_hps_0_hps_io_hps_io_uart0_inst_TX,     --                          .hps_io_uart0_inst_TX
			hps_0_hps_io_hps_io_i2c0_inst_SDA     => CONNECTED_TO_hps_0_hps_io_hps_io_i2c0_inst_SDA,     --                          .hps_io_i2c0_inst_SDA
			hps_0_hps_io_hps_io_i2c0_inst_SCL     => CONNECTED_TO_hps_0_hps_io_hps_io_i2c0_inst_SCL,     --                          .hps_io_i2c0_inst_SCL
			hps_0_hps_io_hps_io_i2c1_inst_SDA     => CONNECTED_TO_hps_0_hps_io_hps_io_i2c1_inst_SDA,     --                          .hps_io_i2c1_inst_SDA
			hps_0_hps_io_hps_io_i2c1_inst_SCL     => CONNECTED_TO_hps_0_hps_io_hps_io_i2c1_inst_SCL,     --                          .hps_io_i2c1_inst_SCL
			hps_0_hps_io_hps_io_gpio_inst_GPIO09  => CONNECTED_TO_hps_0_hps_io_hps_io_gpio_inst_GPIO09,  --                          .hps_io_gpio_inst_GPIO09
			hps_0_hps_io_hps_io_gpio_inst_GPIO35  => CONNECTED_TO_hps_0_hps_io_hps_io_gpio_inst_GPIO35,  --                          .hps_io_gpio_inst_GPIO35
			hps_0_hps_io_hps_io_gpio_inst_GPIO40  => CONNECTED_TO_hps_0_hps_io_hps_io_gpio_inst_GPIO40,  --                          .hps_io_gpio_inst_GPIO40
			hps_0_hps_io_hps_io_gpio_inst_GPIO48  => CONNECTED_TO_hps_0_hps_io_hps_io_gpio_inst_GPIO48,  --                          .hps_io_gpio_inst_GPIO48
			hps_0_hps_io_hps_io_gpio_inst_GPIO53  => CONNECTED_TO_hps_0_hps_io_hps_io_gpio_inst_GPIO53,  --                          .hps_io_gpio_inst_GPIO53
			hps_0_hps_io_hps_io_gpio_inst_GPIO54  => CONNECTED_TO_hps_0_hps_io_hps_io_gpio_inst_GPIO54,  --                          .hps_io_gpio_inst_GPIO54
			hps_0_hps_io_hps_io_gpio_inst_GPIO61  => CONNECTED_TO_hps_0_hps_io_hps_io_gpio_inst_GPIO61,  --                          .hps_io_gpio_inst_GPIO61
			memory_mem_a                          => CONNECTED_TO_memory_mem_a,                          --                    memory.mem_a
			memory_mem_ba                         => CONNECTED_TO_memory_mem_ba,                         --                          .mem_ba
			memory_mem_ck                         => CONNECTED_TO_memory_mem_ck,                         --                          .mem_ck
			memory_mem_ck_n                       => CONNECTED_TO_memory_mem_ck_n,                       --                          .mem_ck_n
			memory_mem_cke                        => CONNECTED_TO_memory_mem_cke,                        --                          .mem_cke
			memory_mem_cs_n                       => CONNECTED_TO_memory_mem_cs_n,                       --                          .mem_cs_n
			memory_mem_ras_n                      => CONNECTED_TO_memory_mem_ras_n,                      --                          .mem_ras_n
			memory_mem_cas_n                      => CONNECTED_TO_memory_mem_cas_n,                      --                          .mem_cas_n
			memory_mem_we_n                       => CONNECTED_TO_memory_mem_we_n,                       --                          .mem_we_n
			memory_mem_reset_n                    => CONNECTED_TO_memory_mem_reset_n,                    --                          .mem_reset_n
			memory_mem_dq                         => CONNECTED_TO_memory_mem_dq,                         --                          .mem_dq
			memory_mem_dqs                        => CONNECTED_TO_memory_mem_dqs,                        --                          .mem_dqs
			memory_mem_dqs_n                      => CONNECTED_TO_memory_mem_dqs_n,                      --                          .mem_dqs_n
			memory_mem_odt                        => CONNECTED_TO_memory_mem_odt,                        --                          .mem_odt
			memory_mem_dm                         => CONNECTED_TO_memory_mem_dm,                         --                          .mem_dm
			memory_oct_rzqin                      => CONNECTED_TO_memory_oct_rzqin,                      --                          .oct_rzqin
			reset_reset_n                         => CONNECTED_TO_reset_reset_n,                         --                     reset.reset_n
			fir_hn_address                        => CONNECTED_TO_fir_hn_address,                        --                    fir_hn.address
			fir_hn_clken                          => CONNECTED_TO_fir_hn_clken,                          --                          .clken
			fir_hn_chipselect                     => CONNECTED_TO_fir_hn_chipselect,                     --                          .chipselect
			fir_hn_write                          => CONNECTED_TO_fir_hn_write,                          --                          .write
			fir_hn_readdata                       => CONNECTED_TO_fir_hn_readdata,                       --                          .readdata
			fir_hn_writedata                      => CONNECTED_TO_fir_hn_writedata,                      --                          .writedata
			fir_hn_byteenable                     => CONNECTED_TO_fir_hn_byteenable                      --                          .byteenable
		);

