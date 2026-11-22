# TangLisp v2+SD（Stage 3b + 3c + load／バイト配列）

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

Stage 3b 時点では読み取り専用。Stage 3c で HEAPIMG.BIN への
上書き保存だけ書き込みを解禁した（下記）。

## Stage 3c：ヒープイメージの保存／復元

REPL で育てた環境（関数・変数の定義）を SD に保存し、次回起動時に
そのまま復元する。Lisp マシンの「昨日の続き」。

- プリミティブ `(save)`：現在のヒープ状態をルートの `HEAPIMG.BIN`
  に書き込む。成功すると `t` を返す
- 起動時：環境初期化のあと `HEAPIMG.BIN` を検査し、ヘッダのマジック
  とチェックサムが正しければ復元して「HEAPIMG restored」と表示し、
  **AUTOEXEC は実行しない**。不正・不在なら従来どおり AUTOEXEC 経路
- 復元後はフリーリスト再構築のため GC を 1 回走らせる

### HEAPIMG.BIN の作り方（事前準備が必須）

ファーム側は FAT のアロケーションもディレクトリエントリの新規作成も
しない。**既存ファイルのクラスタチェーンを辿って上書きするだけ**。
そのため、カードのルートに必要サイズのゼロファイルを PC 側で
あらかじめ置いておくこと。

- 必要サイズ：**12,288 バイト**（24 ブロック、同梱のゼロファイル）
  - ヘッダ 1 ブロック（512 バイト）
  - ペイロードはセル数で変わる（3c 時：11,288 バイト／23 ブロック。
    現在の 950 セル版：9,256 バイト／19 ブロック）。ファイルが
    必要分より大きい分には問題ない（先頭から上書きするだけ）
- このディレクトリに同梱の `HEAPIMG.BIN`（12,288 バイトのゼロ）が
  そのまま使える。自作するなら `dd if=/dev/zero of=HEAPIMG.BIN bs=512 count=24`
- ファイルが小さい／無い場合は `(save)` がエラーを表示し、起動時は
  イメージなしとして AUTOEXEC 経路に落ちる

### イメージフォーマット

先頭ブロックがヘッダ（リトルエンディアン）：

| オフセット | 内容 |
|---|---|
| 0 | マジック `"TLHP"` |
| 4 | バージョン（1） |
| 8 | ヒープ使用セル数 |
| 12 | シンボル数（nsyms） |
| 16 | genv の値 |
| 20 | ペイロードのチェックサム（全バイトの単純合計） |
| 24 | ペイロードバイト数（11,288） |

続くブロックにセル配列・シンボル名バッファ（symtab）・usedbits の
生バイト列をこの順で書く。

### 制約（重要）

- セルもシンボルも**生ポインタ値を含む**ため、イメージが有効なのは
  **同一バイナリ・同一メモリ配置**のときだけ。ファームを再ビルド
  したらイメージは作り直すこと（ペイロードサイズ不一致やチェック
  サム不一致で自動的に無視されるが、配置が変わると検出できない
  場合もあるので過信しない）
- SD 書き込みは CMD24 の単一ブロック書き込みのみ。データ応答
  トークン（下位 5 ビット `00101` = accepted）を確認し、書き込み
  完了まで busy（MISO = 0x00）を上限付きでポーリングする
- SD が無い環境でも REPL は従来どおり使える（`(save)` は失敗を
  表示して `()` を返す）

### ホスト検証（3c、実施済み）

`hosttest/make_fat32.py` に HEAPIMG.BIN（12,288 バイト、クラスタ
5〜10 のチェーン、ゼロ埋め）を追加し、ホスト版の SD 低レイヤにも
イメージファイルへの書き込み（`sd_write_block`）を実装して
2 セッション検証：

- セッション1：起動（HEAPIMG はゼロ＝無効なので AUTOEXEC 実行）
  → `(define myvar 123)`、`(define (square x) (* x x))`、
  `(square 9)` → 81、`(save)` → `save: heap image written` で成功
- セッション2：再起動 → `HEAPIMG restored` と表示され AUTOEXEC は
  実行されず、定義なしで `(fib 10)` → 55、`myvar` → 123、
  `(square 9)` → 81 がそのまま使えた
- 負テスト：ペイロードの 1 バイトを壊したイメージでは
  `HEAPIMG: checksum mismatch` を出して AUTOEXEC 経路に落ちた

## (load) と バイト配列（2026-11-22 追加、PROG35 で実機検証済み）

- `(load LIB.LSP)`：ルートディレクトリの任意ファイルを読み込んで
  評価する特殊形式（名前は評価されないシンボルリテラル、大文字小文字
  不問、8.3 形式）。`(load 'LIB.LSP)` のクォート形も可。最後の式の
  値を返す。AUTOEXEC からも呼べる（バッファは AUTOEXEC 用と別）。
  制約：ファイル上限 1,279 バイト、load の入れ子は不可（エラーになる）
- バイト配列：`(make-bytes n [fill])` / `bytes-ref` / `bytes-set!` /
  `bytes-length` / `bytes?`。タグ 4 の値で、512 バイトの静的アリーナ
  から 8 バイト境界で bump 確保（回収なし）。SD 1 ブロック分の
  バッファが作れるのが狙いで、将来 Lisp でドライバを書く土台。
  制約：アリーナはヒープイメージに含まれないため、バイト配列の
  中身は `(save)`／復元を跨がない（束縛自体は復元される）
- ヒープイメージの版を 1 → 2 に上げた（メモリ配置が変わったため。
  旧イメージは自動で無視され AUTOEXEC 経路に落ちる）

## ハードウェアプリミティブと Lisp 製 SD ドライバ（2026-11-22 追加）

Lisp から直接ハードウェアを触るためのプリミティブを追加した：

- `(peek addr)` / `(poke addr val)`：32bit MMIO アクセス
  （アドレスも値も fixnum の範囲内が前提。UART=0x02000000、
  SPI=0x03000000）
- `(spi-cs 0/1)` / `(spi-fast 0/1)` / `(spi-byte n)`：SPI マスタを
  バイト単位で駆動し、受信バイトを返す
- `(ash n k)` / `(logand a b)` / `(logior a b)`：ビット演算
  （コマンド引数のバイト分割などに必須だった）

その実証として、SD ドライバ自体を TangLisp で書いた
`SDREAD.LSP`（同梱、1,254 バイト）を用意した。CMD0→CMD8→
CMD55/ACMD41 の初期化と CMD17 のブロック読みを全部 Lisp で
行い、ブロック0 のブート署名（510→85、511→170）と
パーティション種別（450→12）を表示する。

ホスト検証は、ホスト版の SD 低レイヤに **SPI バイトレベルの
SD カードエミュレータ**（CMD0/8/55/41/58/17/24 対応、イメージ
ファイル裏付け）を追加して実施：`(load SDREAD.LSP)` で
初期化＋読み取りが成功し、期待値どおりの出力を確認した。

**実機検証も完了（PROG36、2026-11-22）**：カードルートに
SDREAD.LSP（1,252 バイト）を置いて書き込み、UART テスト
6/6 通過。`(load SDREAD.LSP)` が実カードを Lisp ドライバで
初期化してブロック0を読み、t / 85 / 170 / 12 / 12 を表示。
peek/poke 経由でなく SPI プリミティブだけで本物のカードが
読めた。あわせて ash / logior / fib の継続動作も確認。
なお IMG_VERSION を 3 に上げたため、PROG35 で保存した
v2 イメージはこの起動では復元されず AUTOEXEC 経路になった
（仕様どおり）。

なお容量：text 15,193 + bss 16,068 = 31,261 バイト
（スタック約 1.5KB）。バイト配列アリーナは「512 バイトの
ブロック＋ヘッダ」が入るよう 528 バイトに拡大（当初の 512 では
ヘッダ分が溢れて make-bytes 512 が失敗した）。ヒープイメージの
版は 3 に更新。

### 実機検証（PROG35）

- 書き込み成功（STATUS 0x70026020、DONE=1、CRC_ERR=0）
- 起動1回目：旧 v1 イメージを正しく拒否して AUTOEXEC 実行
  （55／2000／42）
- REPL：`(load AUTOEXEC.LSP)` → 42、`(load NOPE.LSP)` →
  `ERR: load: file not found`、バイト配列の作成・読み書き・長さ・
  範囲外エラーすべて期待どおり
- `(save)` で v2 イメージを書き、再書き込み後の起動2回目で復元を
  確認（fib／count が定義なしで動作し、AUTOEXEC では定義されない
  変数 `b` の束縛が残っていた）

## 容量のやりくり（32KB RAM）

- ファーム規模（load／バイト配列版）：text 14,661 + bss 16,052 =
  30,713 バイト（スタック約 2.0KB）。text が 3c 比で増えた主因は
  コンパイラ差（下記）＋ load／バイト配列の実装分
- ファーム規模（3c）：text 12,525 + bss 17,076 = 29,601 バイト
  （スタック約 3.1KB。3b 時点では text 10,633 + bss 17,036 = 27,669）
- v2 からの変更：`-Os` ビルド（v2 は -O2）、ヒープ 1,400 → 1,200 →
  950 セル、ルートスタック 1,024 → 512、AUTOEXEC／load バッファ
  1,280 バイト ×2

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

soc.bin は 808,552 バイト、MD5 `4b76572c452271957377cee3a186e53c`
（SPI プリミティブ版、PROG36・実機検証済み。fs ヘッダの IDCODE
0x0001281b を確認済み。PROG35 版は `e993cacfe0729bde0400f07da7ba2b10`、
3c 版は `022568d6e00cd35da59af7a04f758d1b`）

コンパイラ注意：RISC-V ツールチェーンは VM 入れ替えで消える。
現在のものは `apt install gcc-riscv64-unknown-elf`（13.2.0、
再取得に約11分）。以前のツールチェーンより -Os の text が約2KB
大きいので、容量計算はこの版基準にすること。

## 実機手順（PROG35 で実施済み）

1. PmodMicroSD を Dock 右端に挿し、カード（FAT32）を入れる。
   カードのルートに `AUTOEXEC.LSP` と `HEAPIMG.BIN`（12,288 バイト、
   同梱のもの）を置いておく
2. Termux ホームに top.bin（= ここの soc.bin）と jtag35.py /
   run-jtag35.sh を置く。USB デバイス番号は 001/002 と 001/003 を
   行き来するので、毎回 `termux-usb -l` で確認し、その番号で
   `termux-usb -r` してから `termux-usb -e ~/run-jtag35.sh <device>`
3. UART テストは lisp_test35.py（load／バイト配列／save）、
   再書き込み後は lisp_test35b.py（復元後の fib／count）と
   lisp_test35c.py（復元の証拠に `(bytes? b)`）を使う

## フラッシュ焼き込み（2026-11-22）

PROG36 はコンフィグフラッシュにも焼き込み済みで、電源投入だけで
TangLisp が起動する。フラッシュ用イメージは `soc_flash.bin`
（`python3 ../fs2flash.py soc.fs soc_flash.bin` で生成。JTAG 用の
soc.bin と違いビット反転なし）。焼き込みはスマホ側
`flash_write6.py`＋`run-flashwrite6.sh`（top.bin として
soc_flash.bin を置く）。手順と罠の詳細は ../LISP-MACHINE.md と
~/TOOLS.md の Tang 節。
