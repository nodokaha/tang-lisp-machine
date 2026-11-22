// TangLisp SoC + SPI/SD: PicoRV32 + 32KB BSRAM + UART + SPI master
// RAM  : 0x00000000 - 0x00007FFF
// UART : 0x02000000 DATA (rw), 0x02000004 STATUS (bit0 rx_ready, bit1 tx_busy)
// SPI  : 0x03000000 DATA (write starts an 8-bit mode-0 MSB-first transfer,
//        read returns the received byte)
//        0x03000004 STATUS (bit0 busy)
//        0x03000008 CTRL (bit0 CS assert -> sd_cs driven Low,
//                         bit1 clock select: 0 = slow ~400kHz for SD init,
//                         1 = fast ~4MHz for data transfer; 50MHz input)
// SD pins go to the Dock's right PMOD slot with a Sipeed PMOD TF-CARD v2:
//   sd_sck=C11, sd_mosi=D11 (CMD), sd_miso=B11 (DAT0), sd_cs=G11 (DAT3)
module top(input clk, output uart_tx, input uart_rx, output led,
           output sd_sck, output sd_mosi, input sd_miso, output sd_cs);
  // ---- power-on reset ----
  reg [15:0] rst_cnt = 0;
  reg resetn = 0;
  always @(posedge clk) begin
    if (!resetn) begin
      rst_cnt <= rst_cnt + 1'b1;
      if (rst_cnt == 16'hFFFF) resetn <= 1;
    end
  end

  // ---- CPU bus ----
  wire        mem_valid;
  wire        mem_instr;
  wire [31:0] mem_addr;
  wire [31:0] mem_wdata;
  wire [3:0]  mem_wstrb;
  wire [31:0] mem_rdata;
  wire        mem_ready;

  reg mem_ready_r = 0;
  wire ram_sel  = (mem_addr < 32'h0000_8000);
  wire uart_sel = (mem_addr >= 32'h0200_0000) && (mem_addr < 32'h0201_0000);
  wire spi_sel  = (mem_addr >= 32'h0300_0000) && (mem_addr < 32'h0301_0000);
  always @(posedge clk)
    mem_ready_r <= mem_valid && !mem_ready_r && (ram_sel || uart_sel || spi_sel);
  assign mem_ready = mem_ready_r;
  wire bus_fire = mem_valid && !mem_ready_r;

  picorv32 #(
    .COMPRESSED_ISA(0),
    .ENABLE_MUL(0),
    .ENABLE_DIV(0),
    .ENABLE_IRQ(0),
    .BARREL_SHIFTER(1),
    .STACKADDR(32'h0000_8000),
    .PROGADDR_RESET(32'h0000_0000),
    .PROGADDR_IRQ(32'h0000_0010)
  ) cpu (
    .clk(clk), .resetn(resetn),
    .mem_valid(mem_valid), .mem_instr(mem_instr),
    .mem_ready(mem_ready), .mem_addr(mem_addr),
    .mem_wdata(mem_wdata), .mem_wstrb(mem_wstrb),
    .mem_rdata(mem_rdata),
    .irq(8'b0)
  );

  // ---- RAM: 4 byte banks x 8192 ----
  reg [7:0] bank0 [0:8191];
  reg [7:0] bank1 [0:8191];
  reg [7:0] bank2 [0:8191];
  reg [7:0] bank3 [0:8191];
  initial begin
    $readmemh("fw0.hex", bank0);
    $readmemh("fw1.hex", bank1);
    $readmemh("fw2.hex", bank2);
    $readmemh("fw3.hex", bank3);
  end
  wire [12:0] waddr = mem_addr[14:2];
  reg [31:0] ram_rdata = 0;
  always @(posedge clk) begin
    if (bus_fire && ram_sel) begin
      if (mem_wstrb[0]) bank0[waddr] <= mem_wdata[7:0];
      if (mem_wstrb[1]) bank1[waddr] <= mem_wdata[15:8];
      if (mem_wstrb[2]) bank2[waddr] <= mem_wdata[23:16];
      if (mem_wstrb[3]) bank3[waddr] <= mem_wdata[31:24];
      ram_rdata <= {bank3[waddr], bank2[waddr], bank1[waddr], bank0[waddr]};
    end
  end

  // ---- UART ----
  localparam DIV = 434;
  reg        tx_busy = 0;
  reg [9:0]  tx_frame = 10'h3FF;
  reg [3:0]  tx_idx = 0;
  reg [9:0]  tx_cnt = 0;
  reg [7:0]  rx_byte = 0;
  reg        rx_ready = 0;
  reg        rx_done = 0;
  reg        rx_s1 = 1, rx_s2 = 1;
  reg [1:0]  rx_state = 0;
  reg [9:0]  rx_cnt = 0;
  reg [3:0]  rx_bits = 0;
  reg [7:0]  rx_shift = 0;

  wire [31:0] uart_rdata = (mem_addr[3:2] == 2'd0) ? {24'b0, rx_byte}
                                                   : {30'b0, tx_busy, rx_ready};
  assign mem_rdata = ram_sel ? ram_rdata : spi_sel ? spi_rdata : uart_rdata;
  assign uart_tx = tx_busy ? tx_frame[tx_idx] : 1'b1;

  always @(posedge clk) begin
    rx_done <= 0;
    // bus actions
    if (bus_fire && uart_sel) begin
      if (mem_wstrb != 4'b0) begin
        if (mem_addr[3:2] == 2'd0 && !tx_busy) begin
          tx_frame <= {1'b1, mem_wdata[7:0], 1'b0};
          tx_idx <= 0;
          tx_cnt <= DIV - 1;
          tx_busy <= 1;
        end
      end else begin
        if (mem_addr[3:2] == 2'd0) rx_ready <= 0;
      end
    end
    if (rx_done) rx_ready <= 1;
    // TX FSM
    if (tx_busy) begin
      if (tx_cnt == 0) begin
        tx_cnt <= DIV - 1;
        tx_idx <= tx_idx + 1'b1;
        if (tx_idx == 9) tx_busy <= 0;
      end else tx_cnt <= tx_cnt - 1'b1;
    end
    // RX FSM
    rx_s1 <= uart_rx;
    rx_s2 <= rx_s1;
    case (rx_state)
      0: if (!rx_s2) begin rx_state <= 1; rx_cnt <= DIV/2; end
      1: if (rx_cnt == 0) begin
           if (!rx_s2) begin rx_state <= 2; rx_cnt <= DIV - 1; rx_bits <= 0; end
           else rx_state <= 0;
         end else rx_cnt <= rx_cnt - 1'b1;
      2: if (rx_cnt == 0) begin
           rx_shift <= {rx_s2, rx_shift[7:1]};
           rx_cnt <= DIV - 1;
           rx_bits <= rx_bits + 1'b1;
           if (rx_bits == 7) rx_state <= 3;
         end else rx_cnt <= rx_cnt - 1'b1;
      3: if (rx_cnt == 0) begin
           rx_state <= 0;
           if (!rx_ready) begin rx_byte <= rx_shift; rx_done <= 1; end
         end else rx_cnt <= rx_cnt - 1'b1;
    endcase
  end

  // ---- SPI master (mode 0, MSB first, simple shift register) ----
  // Half-period divider: slow = 62 cycles -> SCK ~403kHz (SD init),
  // fast = 6 cycles -> SCK ~4.2MHz (data). CS is a plain CTRL bit.
  reg        spi_busy = 0;
  reg        spi_sck = 0;
  reg [7:0]  spi_tx = 0;
  reg [7:0]  spi_rx = 0;
  reg [2:0]  spi_bits = 0;
  reg [6:0]  spi_phase = 0;
  reg        spi_cs_assert = 0;
  reg        spi_fast = 0;
  reg        miso_s1 = 1, miso_s2 = 1;
  wire [6:0] spi_div = spi_fast ? 7'd6 : 7'd62;

  assign sd_sck  = spi_sck;
  assign sd_mosi = spi_tx[7];
  assign sd_cs   = ~spi_cs_assert;

  wire [31:0] spi_rdata = (mem_addr[3:2] == 2'd0) ? {24'b0, spi_rx} :
                          (mem_addr[3:2] == 2'd1) ? {31'b0, spi_busy} :
                                                    {30'b0, spi_fast, spi_cs_assert};

  always @(posedge clk) begin
    miso_s1 <= sd_miso;
    miso_s2 <= miso_s1;
    if (bus_fire && spi_sel && mem_wstrb != 4'b0) begin
      if (mem_addr[3:2] == 2'd0 && !spi_busy) begin
        spi_tx <= mem_wdata[7:0];
        spi_bits <= 0;
        spi_phase <= 0;
        spi_sck <= 0;
        spi_busy <= 1;
      end else if (mem_addr[3:2] == 2'd2) begin
        spi_cs_assert <= mem_wdata[0];
        spi_fast <= mem_wdata[1];
      end
    end
    if (spi_busy) begin
      if (spi_phase == spi_div - 1'b1) begin
        spi_phase <= 0;
        if (!spi_sck) begin
          // rising edge: sample MISO
          spi_sck <= 1;
          spi_rx <= {spi_rx[6:0], miso_s2};
        end else begin
          // falling edge: advance MOSI, or finish after the 8th bit
          spi_sck <= 0;
          if (spi_bits == 3'd7) begin
            spi_busy <= 0;
          end else begin
            spi_bits <= spi_bits + 1'b1;
            spi_tx <= {spi_tx[6:0], 1'b1};
          end
        end
      end else spi_phase <= spi_phase + 1'b1;
    end
  end

  // ---- heartbeat LED ----
  reg [24:0] hb = 0;
  always @(posedge clk) hb <= hb + 1'b1;
  assign led = hb[24];
endmodule
