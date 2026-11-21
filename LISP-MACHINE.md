# Tang Primer 25K で LISP マシン — 検討メモ

作成: 2026-11-21夜（清涼の「LISPマシンは作りたい」「desktopで見る」から）
状態: Stage 2 相当まで到達（2026-11-21 深夜）。手組み SoC（LiteX は未使用）＋自作 Lisp「TangLisp v1」が実機で動作。テスト 10/10 通過（fib(10)=55、クロージャ、let、quote、car/cdr）。ファームは ~/workspace/tang/lisp/lisp.c、書き込みは PROG30（jtag30.py）。詳細は Qiita 下書き ~/workspace/your_files/qiita-tang-lisp.md。

## コンセプト

Tang Primer 25K（Gowin GW5A-25）の上に、小さな LISP マシンを作る。
コンソールは FPGA の UART（デバッガのチャンネルB）で、ホストは desktop。
REPL が UART から返ってくる「手触りのある Lisp」が当面のゴールで、
その先にハードウェア Lisp CPU を置く。

## Stage 0: 今夜実証済みの土台（2026-11-21）

- 自作 MPSSE ドライバ（スマホ Termux 経由）で JTAG 疎通、IDCODE 0x0001281b
- SRAM へのビットストリーム書き込み成功（openFPGALoader の gowin.cpp フロー移植）
- OSS CAD Suite（yosys / nextpnr-himbaechel / gowin_pack）で自作設計が動作
- **UART 生死判定**: 50MHz から作った 115200 baud で 0x55 を送信し、
  8秒で 92,160 バイト（理論値ぴったり、全て 0x55）を受信。
  クロック・論理・IO の全経路が正常と確定
- ピン確定: clk=E2（50MHz）、uart_tx=C3、uart_rx=B3、key=K6
- 癖: BL616 デバッガの UART は FTDI 形式の初期化（特に DTR on）をしないと
  データが流れない。IR ラッチは 1 ビットずれる（命令は <<1 して送る）

## ハードウェア制約（GW5A-LV25MG121、Device Version A）

- LUT4: 23,040 / FF: 23,040 / 乗算器: 28 / PLL: 6
- BSRAM: 1,008 Kbit = **126KB**（56ブロック）。← 一番の制約
- S-SRAM: Version A は 0K（内蔵分散 RAM なし）
- ハード CPU なし（ソフトコアを置く）
- SDRAM は外付けモジュール（40ピン ヘッダ、Tang SDRAM 32MB）が別途必要
- フラッシュ: コアボードに 64Mbit SPI Flash（工場デモ入り。当面触らない）

## ルート比較

### A. ソフトコア + C の小さい Lisp（近道）
- LiteX + PicoRV32（実績豊富。SNESTang の iosys は PicoRV32+UART+SD で
  約 2,000 LUT。Sipeed 例題リポジトリに本ボードの LiteX プラットフォーム
  定義（cst）がある）
- その上で小さい Lisp インタプリタを C で動かす
  - 候補: s7 の最小構成（清涼の本命だが素の s7 は大きめ。要ダイエット）、
    uLisp 系の小さい実装、自作の小さい eval（数百〜千行）
- ヒープは BSRAM 内: 64KB 確保できれば cons（8B/セル）で約 8,000 セル。
  玩具としては十分、実用には SDRAM モジュールが欲しくなる
- REPL は UART そのまま。Stage 1 の到達点として現実的

### B. ハードウェア Lisp CPU（本道）
- SECD マシン、またはタグ付きスタックマシンを Verilog で直接実装
- cons ヒープを BSRAM に置き、GC（mark-sweep か copying）を
  ハードウェア/マイクロコードで持つ
- 規模感: PicoRV32 が 1〜2K LUT 級なので、Lisp 専用データパスでも
  23K LUT に十分収まる見込み。問題はメモリ量であって論理量ではない
- 「LISP マシンを作った」と言えるのはこちら。研究メモ的な発展もありうる
  （MCXN947 のセキュリティ研究と並ぶ、手を動かす系の軸として）

### C. ハイブリッド（バイトコード VM）
- Lisp → バイトコードにコンパイルし、VM をハードウェア化。
  A と B の中間だが、今は検討だけ置いておく

## desktop で見る計画（ホスト = desktop）

今夜はスマホ Termux 経由だったが、常用は desktop 直結が本命:

- Tang の USB-C を desktop に挿すと、デバッガ（FT2232 エミュレーション）が
  /dev/ttyUSB0・ttyUSB1 として見える想定。UART コンソールは
  チャンネルB = **/dev/ttyUSB1**、`picocom -b 115200 /dev/ttyUSB1`
  （atomiX プロジェクトが本ボードで同じ構成の実績あり）
- 書き込みは **openFPGALoader -b tangprimer25k**（ボード名で正式サポート）。
  SRAM ロードのみ（-f なし）なら電源入れ直しで工場デモに復帰する
  - 注意: 清涼の個体はシリアル 2023112818 で、openFPGALoader issue #421 の
    「BL616 が 2232H に誤認される」ロットそのもの。現行版には回避策が
    入っているはずだが、desktop 側では最新版を使うこと（Guix の
    パッケージ版が古い場合は OSS CAD Suite 同梱版か自前ビルド）
- ビルド系（OSS CAD Suite）は desktop にも置ける。VM で作って .fs だけ
  運ぶ運用でもよい
- REPL の見え方: desktop のターミナルに Lisp のプロンプトが出る。
  将来はエディタ（Guile/s7 の作業環境）から UART に式を送る形も考えられる

## 段階計画

- **Stage 0（完了）**: JTAG・SRAM 書き込み・UART の土台（スマホ経由）
- **Stage 1**: desktop 直結に移行。openFPGALoader + ttyUSB1 で
  「UART エコー＋プロンプトを返すだけの骨格」を確認
- **Stage 2（到達・2026-11-21）**: 当面は LiteX でなく手組み SoC で PicoRV32 を立て、C の小さい Lisp（TangLisp v1）で eval が回る。GC は mark-sweep＋ルートスタックで評価中も回収可。LiteX 移行（BIOS シリアルブート）は今後の改善候補
  （四則演算と lambda が UART REPL で動く）ところまで
- **Stage 3**: ヒープと GC の設計を詰める。BSRAM で足りなければ
  SDRAM モジュール（40ピン）の導入を判断
- **Stage 4（夢）**: ハードウェア Lisp CPU（ルート B）の設計着手

## 未決定事項

- インタプリタの選択: s7 を削るか、小さい実装を自作するか
- SDRAM モジュールを買うか（NES 化でも必要になる物。12月は支出注意の月）
- 青い PMOD 基板の同定（写真では "pmod J1 REV A"。LED は付いていない模様）
- L6 のユーザー LED の物理的な場所（設計側は駆動できている。
  ドック左の乳白色 LED はデバッガ側で別物と確認済み）
