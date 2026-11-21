module picorv32_regs_ff (
  input clk, input wen,
  input [5:0] waddr, input [5:0] raddr1, input [5:0] raddr2,
  input [31:0] wdata,
  output reg [31:0] rdata1, output reg [31:0] rdata2
);
  reg [31:0] r1 = 0;
  reg [31:0] r2 = 0;
  reg [31:0] r3 = 0;
  reg [31:0] r4 = 0;
  reg [31:0] r5 = 0;
  reg [31:0] r6 = 0;
  reg [31:0] r7 = 0;
  reg [31:0] r8 = 0;
  reg [31:0] r9 = 0;
  reg [31:0] r10 = 0;
  reg [31:0] r11 = 0;
  reg [31:0] r12 = 0;
  reg [31:0] r13 = 0;
  reg [31:0] r14 = 0;
  reg [31:0] r15 = 0;
  reg [31:0] r16 = 0;
  reg [31:0] r17 = 0;
  reg [31:0] r18 = 0;
  reg [31:0] r19 = 0;
  reg [31:0] r20 = 0;
  reg [31:0] r21 = 0;
  reg [31:0] r22 = 0;
  reg [31:0] r23 = 0;
  reg [31:0] r24 = 0;
  reg [31:0] r25 = 0;
  reg [31:0] r26 = 0;
  reg [31:0] r27 = 0;
  reg [31:0] r28 = 0;
  reg [31:0] r29 = 0;
  reg [31:0] r30 = 0;
  reg [31:0] r31 = 0;
  always @(posedge clk) begin
    if (wen) case (waddr[4:0])
      5'd1: r1 <= wdata;
      5'd2: r2 <= wdata;
      5'd3: r3 <= wdata;
      5'd4: r4 <= wdata;
      5'd5: r5 <= wdata;
      5'd6: r6 <= wdata;
      5'd7: r7 <= wdata;
      5'd8: r8 <= wdata;
      5'd9: r9 <= wdata;
      5'd10: r10 <= wdata;
      5'd11: r11 <= wdata;
      5'd12: r12 <= wdata;
      5'd13: r13 <= wdata;
      5'd14: r14 <= wdata;
      5'd15: r15 <= wdata;
      5'd16: r16 <= wdata;
      5'd17: r17 <= wdata;
      5'd18: r18 <= wdata;
      5'd19: r19 <= wdata;
      5'd20: r20 <= wdata;
      5'd21: r21 <= wdata;
      5'd22: r22 <= wdata;
      5'd23: r23 <= wdata;
      5'd24: r24 <= wdata;
      5'd25: r25 <= wdata;
      5'd26: r26 <= wdata;
      5'd27: r27 <= wdata;
      5'd28: r28 <= wdata;
      5'd29: r29 <= wdata;
      5'd30: r30 <= wdata;
      5'd31: r31 <= wdata;
      default: begin end
    endcase
  end
  always @* begin
    case (raddr1[4:0])
      5'd1: rdata1 = r1;
      5'd2: rdata1 = r2;
      5'd3: rdata1 = r3;
      5'd4: rdata1 = r4;
      5'd5: rdata1 = r5;
      5'd6: rdata1 = r6;
      5'd7: rdata1 = r7;
      5'd8: rdata1 = r8;
      5'd9: rdata1 = r9;
      5'd10: rdata1 = r10;
      5'd11: rdata1 = r11;
      5'd12: rdata1 = r12;
      5'd13: rdata1 = r13;
      5'd14: rdata1 = r14;
      5'd15: rdata1 = r15;
      5'd16: rdata1 = r16;
      5'd17: rdata1 = r17;
      5'd18: rdata1 = r18;
      5'd19: rdata1 = r19;
      5'd20: rdata1 = r20;
      5'd21: rdata1 = r21;
      5'd22: rdata1 = r22;
      5'd23: rdata1 = r23;
      5'd24: rdata1 = r24;
      5'd25: rdata1 = r25;
      5'd26: rdata1 = r26;
      5'd27: rdata1 = r27;
      5'd28: rdata1 = r28;
      5'd29: rdata1 = r29;
      5'd30: rdata1 = r30;
      5'd31: rdata1 = r31;
      default: rdata1 = 0;
    endcase
  end
  always @* begin
    case (raddr2[4:0])
      5'd1: rdata2 = r1;
      5'd2: rdata2 = r2;
      5'd3: rdata2 = r3;
      5'd4: rdata2 = r4;
      5'd5: rdata2 = r5;
      5'd6: rdata2 = r6;
      5'd7: rdata2 = r7;
      5'd8: rdata2 = r8;
      5'd9: rdata2 = r9;
      5'd10: rdata2 = r10;
      5'd11: rdata2 = r11;
      5'd12: rdata2 = r12;
      5'd13: rdata2 = r13;
      5'd14: rdata2 = r14;
      5'd15: rdata2 = r15;
      5'd16: rdata2 = r16;
      5'd17: rdata2 = r17;
      5'd18: rdata2 = r18;
      5'd19: rdata2 = r19;
      5'd20: rdata2 = r20;
      5'd21: rdata2 = r21;
      5'd22: rdata2 = r22;
      5'd23: rdata2 = r23;
      5'd24: rdata2 = r24;
      5'd25: rdata2 = r25;
      5'd26: rdata2 = r26;
      5'd27: rdata2 = r27;
      5'd28: rdata2 = r28;
      5'd29: rdata2 = r29;
      5'd30: rdata2 = r30;
      5'd31: rdata2 = r31;
      default: rdata2 = 0;
    endcase
  end
endmodule
