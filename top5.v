module top(input clk, output uart_tx, output led);
  localparam DIV = 434;
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
  assign led = 1'b1;
endmodule
