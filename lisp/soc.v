// TangLisp embryo: PicoRV32 + 32KB BSRAM + UART (115200 @ 50MHz)
// RAM  : 0x00000000 - 0x00007FFF
// UART : 0x02000000 DATA (rw), 0x02000004 STATUS (bit0 rx_ready, bit1 tx_busy)
module top(input clk, output uart_tx, input uart_rx, output led);
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
  always @(posedge clk)
    mem_ready_r <= mem_valid && !mem_ready_r && (ram_sel || uart_sel);
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
  assign mem_rdata = ram_sel ? ram_rdata : uart_rdata;
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

  // ---- heartbeat LED ----
  reg [24:0] hb = 0;
  always @(posedge clk) hb <= hb + 1'b1;
  assign led = hb[24];
endmodule
