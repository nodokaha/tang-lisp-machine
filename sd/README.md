# SD テスト — SoC に SPI を足して SD カードを読む

TangLisp の手組み SoC（PicoRV32 + 32KB RAM + UART）に SPI マスタを追加し、SD カード PMOD 経由でカードの初期化とブロック 0 の読み取りを試すための単体テスト一式。Lisp 本体とは別ファーム（`fw_sd.c`）で、まず配線と SPI の正しさを切り分けるのが目的。

## 対象モジュールと配線

- 対象モジュールは **Digilent PmodMicroSD（410-380、シルク「J1 REV A」）**。以前未同定だった青い PMOD 基板がこれだった。
- **Sipeed PMOD TF-CARD の v1/v2 問題は対象外**（あれは Sipeed 製モジュール側の配線違いの話）。PmodMicroSD は Digilent 標準 PMOD SPI 配線（1=CS, 2=MOSI, 3=MISO, 4=SCK）で、Dock 右端 PMOD スロットに挿したときの FPGA ボールは `../SD-PMOD.md` の v2 表と一致する。

| SPI 信号 | SD 側 | PMOD ピン | FPGA ボール |
|---|---|---|---|
| SCK | CLK | 4 | C11 |
| MOSI | CMD | 2 | D11 |
| MISO | DAT0 | 3 | B11（PULL_MODE=UP） |
| CS | DAT3 | 1 | G11 |

- DAT1/DAT2 は SPI モードでは未使用。カード検出（CD）も使わない。

## 対象カードと読み取り専用の原則

- **対象カードは写真入りのミニカメラ用 microSD（FAT 初期化済み）。テストは読み取りのみで、書き込みはしない。**
- `fw_sd.c` が発行するのは CMD0 / CMD8 / CMD55 / CMD41 / CMD58 / CMD17 のみで、書き込みコマンド（CMD24/25 等）は一切含まない。
- 将来ヒープイメージ等で書き込む場合も FAT 上の専用ファイル経由とし、**生セクタ書き込みが必要になったら事前にユーザーの確認を取る**。

## MMIO マップ（SPI: 0x03000000）

| アドレス | 名前 | 内容 |
|---|---|---|
| +0x00 | DATA | 書くと 8bit 転送開始（SPI mode 0、MSB first）。読むと受信バイト |
| +0x04 | STATUS | bit0 = busy |
| +0x08 | CTRL | bit0 = CS（1 でアサート＝sd_cs を Low 出力）、bit1 = クロック選択（0 = 低速 約400kHz（分周 62×2、SD 初期化用）、1 = 高速 約4.2MHz（分周 6×2、転送用））。読み戻し可 |

既存の割り当て（RAM 0x00000000〜、UART 0x02000000）は不変。

## fw_sd.c の動作

UART（115200）に経過を出しながら：

1. CS 高で 10 バイト（80 クロック）送る
2. CMD0 → R1 = 0x01（idle）を確認
3. CMD8（引数 0x000001AA、CRC 0x87）→ R7 を読み、末尾 0x01 0xAA で SDv2 判定（0x05 が返れば SDv1 として HCS なしで継続）
4. ACMD41（CMD55 + CMD41、SDv2 は HCS ビット付き）→ R1 = 0x00 までリトライ
5. 高速クロックに切り替え、CMD58 で OCR を読み CCS（ブロック／バイトアドレス）を表示
6. CMD17 でブロック 0 を 512 バイト読み、先頭 16 バイトと末尾シグネチャ（0x55 0xAA）を表示
7. 成功したら `SD OK`。失敗したコマンドは番号と応答（R1）を出して停止

RISC-V 側の流儀は `../lisp/lisp.c` と同じ：除算・剰余なし、`-fno-builtin`、memset/memcpy は volatile ループ。

## ビルド手順

```sh
cd sd/
export PATH=~/workspace/oss-cad/oss-cad-suite/bin:$PATH

# ファーム
riscv64-unknown-elf-gcc -march=rv32i -mabi=ilp32 -O2 -fno-builtin \
  -nostdlib -T link.ld crt0.S fw_sd.c -o fw_sd.elf
riscv64-unknown-elf-objcopy -O binary fw_sd.elf fw_sd.bin
# fw_sd.bin をバイトレーン分割して fw0.hex〜fw3.hex（各 8192 行）にする
# （生成スクリプトは lisp/ の従来手順と同じ。soc.v が $readmemh で読む）

# ビットストリーム
yosys -p 'read_verilog -DPICORV32_REGS=picorv32_regs_ff picorv32.v regs_ff.v soc.v; synth_gowin -top top -json soc.json'
nextpnr-himbaechel --device GW5A-LV25MG121NC1 --vopt family=GW5A-25A \
  --vopt cst=tang_sd.cst --json soc.json --write soc_pnr.json
gowin_pack -d GW5A-25A -o soc.fs soc_pnr.json
python3 ../fs2bin.py soc.fs   # ../top.bin に出るので sd/soc.bin へコピー
```

ビルド実績（2026-11-22）：ファーム text 3,221B、LUT4 5,788 / 23,040（25%）、soc.bin 808,552 バイト（MD5 `61148b0fedb85c6e1c3545e74a9f33ca`、fs ヘッダ IDCODE 0x0001281b）。

## 実機テスト手順（前提：モジュールが PmodMicroSD であること）

1. Dock 右端 PMOD スロットに PmodMicroSD を挿し、microSD を入れる
2. スマホ Termux ホームへ `top.bin`（= この `soc.bin`）、`jtag32.py`、`run-jtag32.sh` を置く（書き込みスクリプトは Termux ホームの `top.bin` 固定読み）
3. `run-jtag32.sh` を実行し、`PROG32_DONE`（STATUS の DONE ビット）を確認
4. REPL サーバー／クライアント（`../phone/` の lisp_server.py 等）か UART リスナーで 115200 の出力を読む
5. 期待する出力の締めは `SD OK`。途中で `FAIL CMD<n> R1=0x..` が出たら、そのコマンド番号と応答が切り分け材料

書き込みは SRAM のみ。電源を入れ直すと工場デモに戻る。
