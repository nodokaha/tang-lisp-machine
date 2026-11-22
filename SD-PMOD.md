# Tang Primer 25K Dock — PMOD ピン配置と SD カード PMOD 接続調査

調査日: 2026-11-22
目的: TangLisp の SoC（`lisp/soc.v` / `lisp/tang_lisp.cst`）に SPI を追加し、SD カード PMOD を付けるためのピン確定。コード変更はしていない（本ファイルは調査メモ）。

## 結論（先に要点）

**Sipeed PMOD TF-CARD v2 を Dock の右端 PMOD スロットに挿す**のが、SNESTang / NESTang / C64Nano など実績のあるプロジェクト共通の構成。このとき SPI 4 線は:

| SPI 信号 | SD 側の名前 | FPGA ボール | tang2.cst の番号 |
|---|---|---|---|
| SCK | CLK | **C11** | pmod_io[43] |
| MOSI | CMD | **D11** | pmod_io[40] |
| MISO | DAT0 | **B11**（プルアップ要） | pmod_io[44] |
| CS | DAT3 | **G11** | pmod_io[49] |

- 参考: DAT1 = G10 (pmod_io[48])、DAT2 = D10 (pmod_io[41])。SPI モードでは未使用（SD 仕様では High 固定が建前。実績 cst では IO として確保し PULL_MODE=UP にしている例がある）
- カード検出 (CD) は **B10 (pmod_io[45]) の可能性が高いが未確定**（後述）

根拠は複数プロジェクトの cst がボール単位で完全一致すること（SNESTang `src/boards/primer25k.cst` の「sipeed pmod tfcardv2」定義、NESTang 同名ファイル、C64Nano `src/tang/primer25k/c64nano.cst` の「SDCard sipeed PMOD TFCARD v2」定義）。さらに C64Nano の組み立て説明に「HDMI は左端、SD カードは右端の PMOD スロットへ」と明記がある。

## 1. Dock の PMOD コネクタ

- Sipeed 公式 Wiki: Dock には **PMOD が 3 個**（ほかに 2x20 の 40P ヘッダ、USB-A、ボタン2個）。
- 各 PMOD は Digilent Pmod 標準の **2x6 = 信号8本 + GND + 3.3V**。ピン番号は標準どおり 1〜6 が一列、7〜12 がもう一列で、5/11 = GND、6/12 = VCC(3.3V)。
- 本メモでは位置を **左・中央・右** で呼ぶ（プロジェクトにより PMOD0/1/2 の番号付けが逆向きの場合があるため。例: GitLab の授業用 board_specific.cst は左から pmod_0/1/2、C64Nano は中央を PMOD1・左を PMOD2 と呼ぶ）。
  - 左 = USB-A 側。SNESTang/C64Nano では HDMI (PMOD_DVI) 用
  - 中央 = SNESTang ではコントローラ (PMOD_DS2x2) 用
  - 右 = SD (PMOD_TF-CARD) 用

### コネクタ別対応表

「PMODピン」はモジュール側コネクタのピン番号。[n] は各プロジェクト cst での信号順（上列 1〜4 → [0]〜[3]、下列 7〜10 → [4]〜[7]）。

#### 左 PMOD（GitLab 表記 pmod_0、HDMI 用途）

| PMODピン | [n] | FPGA ボール | tang2.cst |
|---|---|---|---|
| 1 | [0] | F5 | pmod_io[1] |
| 2 | [1] | G7 | pmod_io[2] |
| 3 | [2] | H8 | pmod_io[5] |
| 4 | [3] | H5 | pmod_io[9] |
| 5 | — | GND | — |
| 6 | — | 3.3V | — |
| 7 | [4] | G5 | pmod_io[0] |
| 8 | [5] | G8 | pmod_io[3] |
| 9 | [6] | H7 | pmod_io[4] |
| 10 | [7] | J5 | pmod_io[8] |
| 11 | — | GND | — |
| 12 | — | 3.3V | — |

※ 差動ペアは (1,7) (2,8) (3,9) (4,10) の縦組み。TMDS の割り当て（clk=H5/J5、d0=H8/H7、d1=G7/G8、d2=F5/G5）がこのペア組みと一致することも裏付けになる。

#### 中央 PMOD（GitLab 表記 pmod_1、コントローラ用途）

| PMODピン | [n] | FPGA ボール | tang2.cst |
|---|---|---|---|
| 1 | [0] | A11 | pmod_io[47] |
| 2 | [1] | E11 | pmod_io[54] |
| 3 | [2] | K11 | pmod_io[57] |
| 4 | [3] | L5 | pmod_io[6] |
| 5 | — | GND | — |
| 6 | — | 3.3V | — |
| 7 | [4] | A10 | pmod_io[46] |
| 8 | [5] | E10 | pmod_io[55] |
| 9 | [6] | L11 | pmod_io[56] |
| 10 | [7] | K5 | pmod_io[7] |
| 11 | — | GND | — |
| 12 | — | 3.3V | — |

※ SNESTang の DS2 定義（ds_cs=A11, ds_mosi=E11, ds_miso=K11, ds_clk=L5／2個目: A10, E10, L11, K5）と一致。L5/K5 は BL616 系の予備 UART とも共有されうるピン（C64Nano の注記あり）なので、中央に何か挿す場合は注意。

#### 右 PMOD（GitLab 表記 pmod_2、SD 用途）

| PMODピン | [n] | FPGA ボール | tang2.cst |
|---|---|---|---|
| 1 | [0] | G11 | pmod_io[49] |
| 2 | [1] | D11 | pmod_io[40] |
| 3 | [2] | B11 | pmod_io[44] |
| 4 | [3] | C11 | pmod_io[43] |
| 5 | — | GND | — |
| 6 | — | 3.3V | — |
| 7 | [4] | G10 | pmod_io[48] |
| 8 | [5] | D10 | pmod_io[41] |
| 9 | [6] | B10 | pmod_io[45] |
| 10 | [7] | C10 | pmod_io[42] |
| 11 | — | GND | — |
| 12 | — | 3.3V | — |

### tang2.cst 全64ピンの内訳（突き合わせ結果）

tang2.cst の pmod_io[0..63] は PMOD 専用ではなく「Dock の汎用 IO 全部」の一括リストだった。内訳:

- PMOD 3スロット × 8 = 24 本（上表）
- 40P ヘッダ側 GPIO 38 本（SDRAM モジュール用。SNESTang の SDRAM 定義と一致: K2,K1,L1,L2,K4,J4,G1,G2,E1,A1,F2,F1,B2,C2,L4,L3,F6,F7,J10,J11,H4,G4,H2,H1,J2,J1,D1,E3,J7,K7,L8,L7,K10,L10,K9,L9,K8,J8）
- 基板ボタン 2 本: H10 / H11（pmod_io[50] / [51]。Sipeed 公式例題の issue でも「ボタンは H10/H11」と指摘されている）

## 2. SD カード PMOD モジュール側の割り当て

### Sipeed PMOD_TF-CARD

- 公式 Wiki (TANG PMOD) の説明は「標準 TF カード対応、カード検出機能つき」のみで、ピン表は載っていない。回路図はダウンロードパッケージ側で、今回の調査では直接読めていない（未確定事項参照）。
- 実質的な定義は利用プロジェクトの cst が担っている。**v1 と v2 で配線が違う**ので要注意。

#### v2（現行。基板シルク「PMOD-TF CARDv2」）— 右スロット前提

| PMODピン | SD 信号 | SPI での役割 | FPGA ボール |
|---|---|---|---|
| 1 | DAT3 | CS | G11 |
| 2 | CMD | MOSI | D11 |
| 3 | DAT0 | MISO | B11 |
| 4 | CLK | SCK | C11 |
| 7 | DAT1 | 未使用 | G10 |
| 8 | DAT2 | 未使用 | D10 |
| 9 | （CD と推定） | カード検出 | B10 |
| 10 | （WP または NC と推定） | — | C10 |

これは Digilent 標準の PmodSD / Pmod MicroSD のピン割り当て（1=CS, 2=MOSI, 3=MISO, 4=SCK, 7=DAT1, 8=DAT2, 9=CD, 10=WP/NC）と一致する。つまり v2 は「標準 PMOD SD 配線そのもの」。

#### v1（旧・廃止扱い）

C64Nano の cst に「old outdated version / not working!」と注記付きで残っている定義:

| SD 信号 | FPGA ボール | （右スロットの PMODピンに換算すると） |
|---|---|---|
| CLK | D10 | 8 |
| CMD (MOSI) | D11 | 2 |
| DAT0 (MISO) | B11 | 3 |
| DAT1 | C11 | 4 |
| DAT2 | G11 | 1 |
| DAT3 (CS) | G10 | 7 |

CMD と DAT0 は v2 と同じだが、CLK / DAT1 / DAT2 / DAT3 が別のピンに回っている。手元のモジュールが v1 か v2 かで cst を間違えると動かない。**基板のシルクで版を確認すること**（NanoMig PR #30 もこの食い違いが主題。SNESTang は 2024 年頃から v2 前提に移行、C64Nano は「PMOD TF-CARD V2 is required」）。

### Digilent 標準型（参考）

PmodSD / Pmod MicroSD の公式マニュアルの J1 定義: 1=~CS, 2=MOSI, 3=MISO, 4=SCK, 5=GND, 6=VCC, 7=DAT1, 8=DAT2, 9=CD, 10=WP(PmodSD) / NC(Pmod MicroSD), 11=GND, 12=VCC。Sipeed v2 と同じ並びなので、標準型モジュールでも右スロットで同じボール割り当てになるはず。

## 3. TangLisp SoC への接続案（確定分）

`tang_lisp.cst` に足す想定の割り当て（コード変更はまだしない）:

```
IO_LOC "sd_sck"  C11;   // PMOD右 pin4
IO_LOC "sd_mosi" D11;   // PMOD右 pin2 (SD CMD)
IO_LOC "sd_miso" B11;   // PMOD右 pin3 (SD DAT0) — PULL_MODE=UP
IO_LOC "sd_cs"   G11;   // PMOD右 pin1 (SD DAT3)
```

- MISO (DAT0) はプルアップ指定が実績 cst の共通項（SNESTang は DAT0 のみ PULL_MODE=UP、C64Nano は全 SD 線 UP）。
- DAT1/DAT2 は SPI では使わない。浮かせるとカード側の状態が不定になることがあるため、使う場合は G10/D10 も IO として High 固定かプルアップに寄せるのが無難（要設計判断）。
- 電圧は PMOD の VCC = 3.3V で、既存 cst と同じ LVCMOS33 / BANK_VCCIO=3.3 で整合する。

## 4. 未確定事項（推測で断言しない部分）

1. **カード検出 (CD) のピン**: Sipeed 公式回路図を直接確認できていない。Digilent 標準（pin9=CD）と、右スロットで残る信号ピンが B10 (pin9) / C10 (pin10) の2本であることからの推定で CD=B10 としたが、確定には ①回路図パッケージの確認、または ②実機で B10/C10 を入力にしてカード抜き差しで変化を見る、のどちらかが要る。TangLisp の初期実装では CD を使わない前提でよい。
2. **手元モジュールの版数**: ユーザー所持の SD PMOD が v1 か v2 かはシルク未確認。v2 前提で話を進めているが、実機作業の前に基板表記の確認が必要。
3. **左右の向き**: 「右端」は基板を上面から見て USB-A 側を左とした場合の右。C64Nano の記述（HDMI=leftmost、SD=rightmost）と SNESTang の組み立て写真が根拠。実物と写真を照らして最終確認すること。
4. **公式回路図そのもの**: Sipeed のダウンロードステーションにある Dock 回路図 PDF は今回開けていない（Wiki 本文にはピン表がない）。上表は「複数プロジェクトの cst の一致＋tang2.cst との突き合わせ」で、回路図との照合は未実施。
5. Sipeed 公式例題リポジトリ (TangPrimer-25K-example) の pmod_led 例にはピン不一致の issue (#11) があり、公式例の cst は鵜呑みにしない方がよい（本メモは公式例ではなく実働プロジェクトの cst を主根拠にした）。

## 出典

- Sipeed 公式 Wiki — Tang Primer 25K（PMOD 3個、Dock 仕様、例題リポジトリへのリンク）: https://en.wiki.sipeed.com/hardware/en/tang/tang-primer-25k/primer-25k.html
- Sipeed 公式 Wiki — TANG PMOD（PMOD_TF-CARD の紹介、カード検出つき）: https://wiki.sipeed.com/hardware/en/tang/tang-PMOD/FPGA_PMOD
- GitLab (Innopolis 大の授業資料) — boards/tang_primer_25k_dock_dvi/board_specific.cst（左/中央/右 PMOD の [0..7] とボールの対応の主根拠）: https://gitlab.pg.innopolis.university/sum25-acd/basics-graphics-music/-/blame/c057b0c29c217c20403bdf3c164c5520ab11e256/boards/tang_primer_25k_dock_dvi/board_specific.cst
- GitHub nand2mario/snestang — `src/boards/primer25k.cst`（「sipeed pmod tfcardv2」定義、DS2 定義、SDRAM 定義）／組み立て説明（コントローラは中央スロット）: https://github.com/nand2mario/snestang/blob/main/doc/installation.md
- GitHub nand2mario/nestang — `src/boards/primer25k.cst`（SD 定義が SNESTang と同一）
- GitHub MiSTle-Dev/C64Nano — `src/tang/primer25k/c64nano.cst`（TF v2 の有効定義と v1 の旧定義・「not working」注記）／`TANG_PRIMER_25K.md`（HDMI=左端、SD=右端、V2 必須）
- GitHub MiSTle-Dev/NanoMig PR #30（v1/v2 食い違いの報告、SNESTang 定義が典拠）: https://github.com/MiSTle-Dev/NanoMig/pull/30
- Digilent Pmod MicroSD Reference Manual（標準 PMOD SD 配線）: https://www.farnell.com/datasheets/4376762.pdf
- Digilent PmodSD Reference Manual: https://static.chipdip.ru/lib/779/DOC011779588.pdf
- 手元資料: `tang2.cst`（pmod_io[0..63] とボールの対応、全ピン突き合わせに使用）、`lisp/tang_lisp.cst`（現行 SoC は clk/uart/led のみ）
