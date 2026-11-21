# Tang Primer 25K で作る LISP マシン

スマホ 1 台と FPGA ボード 1 枚で、自作 JTAG ドライバ → PicoRV32 ソフトコア SoC → 小さい Lisp インタプリタ「TangLisp」までを積み上げたプロジェクト。Qiita 連載のコード置き場で、記事の回ごとにここへ材料が増えていく。

- ボード：Tang Primer 25K（Gowin GW5A-LV25MG121、Device Version A）＋ Dock
- 開発マシン：Android スマホの Termux（書き込み・コンソールも全部スマホ）

## 連載（Qiita）

- 第1回：[スマホだけで FPGA に Lisp マシンを作った話（Tang Primer 25K＋自作JTAG＋PicoRV32）](https://qiita.com/nodokaha/items/54e0f4032e887c0f95dd)（原稿：`articles/01-tang-lisp.md`）
- 第2回以降の候補：LiteX 移行と BIOS シリアルブート、SDRAM モジュールでヒープ拡張、ハードウェア Lisp CPU（本道）。設計メモは `LISP-MACHINE.md`

## 構成

- `lisp/` — SoC とファームウェア
  - `soc.v`：PicoRV32＋32KB RAM＋UART の最小 SoC
  - `regs_ff.v`：Version A（分散 RAM なし）向けの FF 版レジスタファイル
  - `lisp.c`：TangLisp v1 本体（reader／eval／クロージャ／mark-sweep GC）
  - `fw_echo.c`：胚（エコーファーム）、`crt0.S`、`link.ld`、`tang_lisp.cst`
  - `picorv32.v`：YosysHQ/picorv32（ISC License）
- `phone/` — スマホ Termux 側のツール群
  - `jtag30.py`：自作 JTAG ドライバ（BL616 の癖対策入り、SRAM 書き込み）
  - `uart_listen2.py`：UART 生死判定（DTR が要点）
  - `lisp.py`：ワンショット送信（send.txt 方式）、`lisp_test.py`：テスト 10 本
  - `lisp_repl.py`：対話 REPL（termux-usb 直結版）
  - `lisp_server.py`／`lisp_client.py`：サーバー／クライアント分離版 REPL（出力をリアルタイムに流すための本命）
  - `run-*.sh`：termux-usb 用ラッパー
- `top.v`〜`top5.v`、`tang*.cst` — 初期実験（LED 点灯確認、UART ストリーマ）
- `fs2bin.py` — `.fs` → バイナリ変換（コメント行除去＋全バイト bit 反転）
- `LISP-MACHINE.md` — 設計検討メモ
- `articles/` — Qiita 原稿の置き場

## TangLisp v1 の仕様（要約）

- 値：31bit fixnum、nil（= 空リスト、唯一の偽）、cons、シンボル（96 種・15 文字まで）、クロージャ
- 特殊形式：`quote` `if` `lambda` `define`（関数糖衣・自己再帰可）`let`（並行束縛）`begin`
- プリミティブ 15 個：`+` `-` `*` `=` `<` `>` `cons` `car` `cdr` `null?` `pair?` `eq?` `not` `list` `print`
- GC：mark-sweep、ヒープ 1,400 セル、ルートスタック付きで評価中も回収可
- 末尾再帰最適化なし、`set!` なし（コードはあるが未接続）

## ビルドと書き込み（概要）

- ツールチェーン：OSS CAD Suite（yosys `synth_gowin` → nextpnr-himbaechel `--device GW5A-LV25MG121NC1 --vopt family=GW5A-25A` → gowin_pack）、ファームは RISC-V gcc（`-march=rv32i -mabi=ilp32 -fno-builtin`）
- 書き込みは SRAM のみ。フラッシュには書かないので、電源を入れ直すと工場デモに戻る
- デバッガ（BL616）の癖 3 点（入力経路の固着→USB リセット、IR の 1 ビットずれ→命令を <<1、UART は DTR を立てないと流れない）は第1回の記事に詳しく書いた

## ライセンス

- `lisp/picorv32.v` は YosysHQ/picorv32 の配布物（ISC License、Copyright Claire Xenia Wolf）
- それ以外は未設定（必要になったら決める）
