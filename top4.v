module top(input clk, output uart_tx, output led);
  localparam DIV = 434; // 50MHz / 115200
  reg [15:0] cnt = 0;
  reg [3:0] idx = 0;
  wire [9:0] frame = {1'b1, 8'h55, 1'b0};
  assign uart_tx = frame[idx];
  always @(posedge clk) begin
    if (cnt == DIV - 1) begin
      cnt <= 0;
      idx <= (idx == 9) ? 0 : idx + 1'b1;
    end else cnt <= cnt + 1'b1;
  end
  reg [24:0] lc = 0;
  reg lo = 0;
  always @(posedge clk) begin
    if (lc == 25_000_000) begin
      lc <= 0;
      lo <= !lo;
    end else lc <= lc + 1'b1;
  end
  assign led = lo;
endmodule
