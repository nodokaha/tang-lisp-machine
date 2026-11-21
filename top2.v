module top(input clk, input key, output led, output [63:0] pmod_io);
  reg [31:0] count = 0;
  reg [7:0] state = 8'b00000001;
  reg led_out = 0;
  always @(posedge clk) begin
    if (!key) begin
      count <= 0;
      state <= 8'b00000001;
      led_out <= 0;
    end else if (count <= 32'd9999999)
      count <= count + 1'b1;
    else begin
      count <= 0;
      led_out <= !led_out;
      state <= {state[6:0], state[7]};
    end
  end
  genvar i;
  generate for (i = 0; i < 8; i = i + 1)
    assign pmod_io[i*8+7:i*8] = ~state;
  endgenerate
  assign led = led_out;
endmodule
