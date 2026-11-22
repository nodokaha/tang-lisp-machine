# TangLisp v2+SD（Stage 3b）

TangLisp v2（`../lisp/lisp.c`）に SD／FAT32 読み取りを統合したファーム。
SoC は `../sd/` の SPI 追加版（MMIO 0x03000000、ピンは `../SD-PMOD.md`：
Digilent PmodMicroSD を Dock 右端スロット、SCK=C11／MOSI=D11／MISO=B11／CS=G11）。

## 起動時の動作

1. バナー「TangLisp v2+SD」
2. 環境（シンボル／プリミティブ）を初期化
3. SD 処理：
   - SD 初期化（CMD0/8/55/41/58、fw_sd.c の実績コード）
   - ブロック0 を MBR としてパーティション種別と開始 LBA を表示
     （種別 0x0B/0x0C = FAT32、0x07 は exFAT 系の可能性。パーティションが
     無くブロック0 自体が BPB のスーパーフロッピー形式にも対応）
   - BPB の OEM 名が "EXFAT" なら exFAT と明示表示して SD 処理を中止
   - FAT32 としてマウントできたらルートディレクトリの一覧
     （8.3名＋サイズ）を表示。LFN（attr 0x0F）・削除エントリ・
     ボリュームラベルはスキップ
   - `AUTOEXEC.LSP` があれば読み込んで（上限 2048 バイト）、
     トップレベル式を順に評価し、結果を `AUTOEXEC> ` 接頭辞つきで表示。
     define した関数はそのまま REPL で使える
   - SD が無い／失敗した場合はその旨を表示して通常 REPL に入る
4. 通常 REPL

読み取り専用。カードへの書き込みは一切しない。

## 容量のやりくり（32KB RAM）

- ファーム規模：text 10,633 + bss 17,036 = 27,669 バイト（スタック約 5KB）
- v2 からの変更：`-Os` ビルド（v2 は -O2）、ヒープ 1,400 → 1,200 セル、
  ルートスタック 1,024 → 512、AUTOEXEC バッファ 2,048 バイト
  （当初 4,096 で設計したがリンクが 3,908 バイト超過したため縮小）

## ホスト検証（実施済み）

`hosttest/make_fat32.py` で MBR 付き FAT32 イメージを自作
（dosfstools／mtools が VM に無いため。種別 0x0C、開始 LBA 2048、
ルートに AUTOEXEC.LSP と DUMMY.TXT、LFN・削除・ボリュームラベルの
エントリも混ぜてある）。`hosttest/make_host_sd.py` で lisp_sd.c の
SD 低レイヤ（`SDLOW_BEGIN`〜`END`）をイメージファイル読みに差し替えた
ホスト版をビルドし、以下を確認：

- パーティション種別 0x0C の表示、FAT32 パラメータ解析
- ルート一覧に AUTOEXEC.LSP（184バイト）と DUMMY.TXT のみ表示
- AUTOEXEC 実行：`(fib 10)` → 55、末尾再帰 `(count 2000 0)` → 2000、
  `(+ 40 2)` → `AUTOEXEC> 42`
- 実行後も REPL が使え、AUTOEXEC の define が残っている
- SD イメージが無い場合：`SD: unavailable` を出して REPL に入る
- exFAT イメージ（種別 0x07＋OEM "EXFAT"）：検出を明示して REPL に入る

## ビルド

```
riscv64-unknown-elf-gcc -march=rv32i -mabi=ilp32 -Os -fno-builtin \
  -nostdlib -T link.ld crt0.S lisp_sd.c -o fw.elf
riscv64-unknown-elf-objcopy -O binary fw.elf fw.bin
# fw.bin をバイトレーン分割して fw0..3.hex（各 8192 行）
export PATH=~/workspace/oss-cad/oss-cad-suite/bin:$PATH
yosys -p 'read_verilog -DPICORV32_REGS=picorv32_regs_ff picorv32.v regs_ff.v soc.v; synth_gowin -top top -json soc.json'
nextpnr-himbaechel --device GW5A-LV25MG121NC1 --vopt family=GW5A-25A \
  --vopt cst=tang_sd.cst --json soc.json --write soc_pnr.json
gowin_pack -d GW5A-25A -o soc.fs soc_pnr.json
python3 ../fs2bin.py soc.fs   # 出力は ../top.bin に固定なので soc.bin へコピー
```

利用率：LUT4 5,788 / 23,040（25%）。soc.bin は 808,552 バイト、
MD5 `1022062476f152cfa429f8b4fab39b49`。

## 実機手順（未実施）

1. PmodMicroSD を Dock 右端に挿し、カード（FAT32）を入れる。
   カードのルートに `AUTOEXEC.LSP` を置いておくと起動時に実行される
2. Termux ホームに top.bin（= ここの soc.bin）と jtag33.py /
   run-jtag33.sh を置き、`termux-usb -e ~/run-jtag33.sh /dev/bus/usb/001/002`
3. UART 出力でパーティション種別・ルート一覧・AUTOEXEC の結果を見る
   （PROG33_DONE が書き込み成功の印）
