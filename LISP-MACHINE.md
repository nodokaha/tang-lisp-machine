# Tang Primer 25K で LISP マシン — 検討メモ

作成: 2026-11-21夜（清涼の「LISPマシンは作りたい」「desktopで見る」から）
状態: Stage 2 相当まで到達（2026-11-21 深夜）。手組み SoC（LiteX は未使用）＋自作 Lisp「TangLisp v1」が実機で動作。テスト 10/10 通過（fib(10)=55、クロージャ、let、quote、car/cdr）。ファームは ~/workspace/tang/lisp/lisp.c、書き込みは PROG30（jtag30.py）。詳細は Qiita 下書き ~/workspace/your_files/qiita-tang-lisp.md。
更新（2026-11-22、TangLisp v2）: `set!` を接続し、末尾再帰最適化（eval のトランポリン化）を実装。ホスト版テスト 37 件全通過（`set!`／カウンタ・クロージャ／末尾再帰カウンタ等を含む）。ファーム規模 text 8,616＋bss 18,140＝26,756 バイト（32KB 内）。ビットストリーム再生成済み（lisp/soc.fs → top.bin／lisp/soc.bin、801,904 バイト）。書き込みは PROG31（phone/jtag31.py＋run-jtag31.sh、スマホ側は新 top.bin を使う）。**実機書き込み・実機テストは未実施**（ボード接続待ち）。

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
- **Stage 3（方針決定・2026-11-22）**: ヒープ拡張は SDRAM モジュール購入ではなく、
  **手持ちの SDカード PMOD** で進める（清涼の提案）。段階は：
  - 3a: SoC に SPI 追加（MMIO 0x03000000）＋ SD 初期化・ブロック読みテスト
    （ピンは SD-PMOD.md で確定：v2 モジュール＋Dock 右端スロットで
    SCK=C11／MOSI=D11／MISO=B11／CS=G11。実機前にモジュールの v1/v2 確認が要る）
  - 3b: 起動時に SD から Lisp ソースを読み込んで実行（ファーム焼き直しなしで
    プログラム差し替え＝ラズパイ的な単体動作の入口）
  - 3c: ヒープイメージの保存／復元（REPL の状態ごと寝かせて続きから再開）
    （3a〜3c は 2026-11-22 に実機完了）
  - 3b+: `(load NAME)` で SD 上の任意ファイルを実行できるようにした
    （ライブラリ読み込み。2026-11-22 実機完了、PROG35）
  - 土台（Stage 4 の前提）：バイト配列（make-bytes 等、アリーナ 528B）を
    追加（2026-11-22 実機完了、PROG35）。続けて peek/poke・SPI
    プリミティブ＋ビット演算も追加し、SD ドライバを TangLisp 自身で
    書いた（SDREAD.LSP、PROG36 で実機検証完了：実カードの初期化と
    ブロック0読みを Lisp だけで実行）。
    「ドライバを Lisp で書く」形が成立したので、W5500 等の
    ネットワークドライバも同じ流儀で書ける
  - 3d: FAT32 ファイル作成の一般化＋名前付き世界 (save NAME)/(restore NAME)
    （2026-11-23 実機完了、PROG37。実機11/11、フラッシュ焼き済み。
    ページング式スワップは生ポインタ前提のため不採用とし、大容量ヒープは
    TANG_SDRAM 到着後に回す）
- **Stage 4**: ネットワーク。ESP 系モジュールを UART／PMOD で付けて TCP REPL
  （まずは telnet 相当）→ その先に ssh。ssh は TCP/IP＋暗号で RAM 32KB に
  入らないため Stage 3 のメモリ拡張が前提（USB WiFi ドングルの直接駆動は
  USB ホストが必要で非現実的、という整理も 2026-11-22）
- **Stage 5（夢）**: ハードウェア Lisp CPU（ルート B）の設計着手。
  2026-11-22夜、清涼の希望で「RISC-V ではなく元祖 Lisp マシン式の
  独自アーキテクチャ」と方向が固まり、叩き台を LISP-CPU.md に作成
  （タグ付きワード＋CDR コーディング＋マイクロコード＋GC ハード補助）。
  同夜、SECD 型の叩き台も LISP-CPU-SECD.md に作成（全状態がヒープ＝
  リストであることを中心に置く型。元祖式と対で検討する）。
  言語目標は R7RS-small を置く方向（同夜）。call/cc と
  dynamic-wind が必須級になるため SECD 型の裏付けが強まる。
  ライブラリの置き場所は SD、数値タワー／文字列／syntax-rules は
  段階化の論点として SECD メモに記録
  **移行線引き（2026-11-24 決定）**：TangLisp を母艦（黄金参照）
  として残し、ネイティブは設計と SECD コンパイラ／シミュレータ
  から始める。TangLisp の大ヒープ化と言語の大型拡張はやらない。
  乗り換えの合図は「仕様凍結／シミュレータがテスト通過／SDRAM
  到着」の3つ。詳細は FIRMWARE.md の移行線引きの節

## 未決定事項

- インタプリタの選択: s7 を削るか、小さい実装を自作するか
- SDRAM モジュールを買うか（Stage 3 は SD で進めることにしたため当面不要。
  NES 化では別途必要になる物。12月は支出注意の月）
- SD PMOD モジュールの v1／v2 判別（シルク確認。ピン配置が違うため実機前に必須）
- 青い PMOD 基板の同定（写真では "pmod J1 REV A"。LED は付いていない模様。
  SD PMOD 本人ではないかという疑いあり・2026-11-22）
- L6 のユーザー LED の物理的な場所（設計側は駆動できている。
  ドック左の乳白色 LED はデバッガ側で別物と確認済み）

## コンフィグフラッシュ焼き込み（2026-11-22夜、実機完了）

- 自作 JTAG ドライバに GW5A の外部 SPI フラッシュ書き込みを実装し、
  PROG36 をコンフィグフラッシュへ焼き込んだ。電源投入／RELOAD で
  TangLisp がフラッシュから起動する（UART テスト 6/6 で確認済み）。
  これで PC に挿せばそのまま Lisp マシンとして立ち上がる。
- フラッシュは XTX XT25F64B（JEDEC 0x0B4017、64Mbit）。書き込み経路は
  GW5A の JTAG-SPI ブリッジ（命令 0x16）。実装は phone/flash_write6.py
  （openFPGALoader の programExtFlash 相当を移植）。
- **最大の教訓：フラッシュ用イメージは .fs の生パッキング（ビット反転
  なし）**。JTAG/SRAM 用の反転形式（fs2bin.py）を焼いたら照合は完全
  一致でも自動起動が2回とも失敗した（同期ワード後の命令バイトが
  0x06→0x60 に化ける）。変換は fs2flash.py、PROG36 のフラッシュ
  イメージは lisp-sd/soc_flash.bin（808,552B、MD5 8e148e4e…）。
- 工場イメージのバックアップはスマホの ~/flash_backup.bin と
  ~/workspace/tang/flash_backup.bin（先頭 851,968B。ただし読み出し
  経路の末尾バイト癖のため各 256B チャンク末尾バイトは不正確な
  可能性あり——完全な復元保証はない）。
- 細かい罠は ~/TOOLS.md の Tang 節に集約（RDSR の WEL/WIP が読めない
  件、読み出し +1 バイト、SPI モード脱出ダンスの形、他）。
- Qiita 第3弾（ヒープ保存／(load)／Lisp 製 SD ドライバ／フラッシュ焼き込み）は
  2026-11-22 夜に公開済み：https://qiita.com/nodokaha/items/c54689997210ffb697cf
  （原稿 articles/03-tang-lisp-flash.md、写真入り）

## その先の構想：Flipper Zero 的なデバイス化（2026-11-22夜、清涼との雑談から）

実装計画は FIRMWARE.md（2026-11-24 に3方向＝顔／お世話係／土台で合意）。
第1歩の起動ランチャは PROG38 で完成（2026-11-24 実機検証：
SRAM テスト 4/4＋3/3、フラッシュ VERIFY OK、単体起動で
メニュー→HEAPIMG 復元まで確認）。

フラッシュ単体起動ができたことで、次の絵として「Flipper Zero みたいな
端末」という方向が出てきた（Loko Scheme のような「Lisp が OS の顔になる」
形にも重なる）。部品の対応：

- **SD＝システムディスク／カートリッジ**：起動時の AUTOEXEC がそのまま
  ランチャになり、.LSP の「アプリ」が並ぶ。ヒープイメージ（ワールド）も
  名前を分けて複数置き、起動時に選べるようにする
- **アプリストア**：アプリはテキスト（.LSP）なので、ストアは
  GitHub リポジトリ＋索引ファイルで足りる。ダウンロードと転送は
  スマホ側が担い、基板はネットに出ない
- **Android 相棒アプリ**：2段階で考える。軽い版＝シリアル端末＋
  ゲームパッド面（UART に文字を送るだけ、基板無改造。ゲームの操作盤
  にもなる）。育てた版＝SD ファイル管理（.LSP の送り込み、ワールドや
  ログの受け取り）
- **Bluetooth は UART 接続モジュールで**：USB ドングルは USB ホストが
  必要で非現実的（WiFi ドングルと同じ壁）。HM-10 系や Pmod BLE
  （RN4871）、ESP32 PMOD のような「無線 UART」なら PMOD に挿すだけ。
  役割は Flipper と同じく「スマホアプリとのケーブル代わり」
- **顔**：到着待ちの PMOD-TFTLCD（ILI9341）がデバイスの画面になる。
  入力は Dock ボタン／USB キーボード等が候補

関門は共通でひとつ：**SD 書き込みの一般化**（現状は既存ファイルの
クラスタ上書きのみ）。受けたファイルの新規保存、マシン上で書いた
プログラムの保存には、書き込み側の一般化が要る。

購入メモ（2026-11-22夜）：無線担当の候補として清涼が Pocket-Dongle-S3
（ESP32-S3 の USB ドングル、N16R8 表記、0.96 インチ LCD、AliExpress
GNPE 出品）を購入、到着待ち。出品説明に PSRAM の明記がなかったため、
到着したらまず PSRAM 8MB の実在を実機確認すること。UART の引き出し
方法（端子／パッド）も要確認。
