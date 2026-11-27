#!/usr/bin/env python3
"""SECD マシンのホスト側シミュレータ（叩き台）。

位置づけ: LISP-CPU-SECD.md の「順番」の 1 段目と 2 段目。
  1. SECD エミュレータで機械を模倣する（ここではホスト側 Python 版。
     TangLisp 版を書く前に、命令の意味とコンパイラの形を確かめる）
  2. 遷移カウンタで熱い所を測る（どの命令が何回走り、LD が何ホップ辿るか）
  3. 測った結果で仕様を凍結する（まだ先）

命令セットは LISP-CPU-SECD.md の叩き台どおり。DUM／RAP は当初
未決定だったが、2026-11-27 の計測（Z コンビネータ経由では呼び出し
1回あたり AP／RTN が4回になる）を受けて清涼が「入れて測り直す」
と決めたため実装した。再帰は letrec（DUM／RAP）でも Y コンビネータ
でも書ける（比較のため両方のテストを残す）。TAP は未決定のため
入れていない。RTN は末尾位置でも D を経由する（＝末尾再帰は今は
最適化されない）。

使い方: python3 secd_sim.py
"""

# ---------------------------------------------------------------- 値
# 値は Python のまま: int, bool, None(=nil), list(cons セルの代わり),
# ('closure', code, env) がクロージャ。シンボルは str。
NIL = None


def is_true(v):
    return v is not False and v is not NIL


# ------------------------------------------------------- コンパイラ
# compile(expr, env, code) -> 命令列（リスト）。env はフレーム（名前の
# リスト）のリスト。古典的な Lispkit 流の後置コンパイル。
#
# 式の形: 数値 | シンボル | (quote v) | (if c t e)
#        | (lambda (x...) body) | (let ((x v)...) body)
#        | (letrec ((x v)...) body)
#        | (f a1 a2 ...)   ※ f は式。プリミティブは名前で呼ぶ
# プリミティブ: + - * / = < car cdr cons atom? null?

PRIMS = {
    '+': 'ADD', '-': 'SUB', '*': 'MUL', '/': 'DIV', '=': 'EQ',
    '<': 'LT', 'atom?': 'ATOM', 'null?': 'NULL?',
}
# car/cdr/cons は PRIM ではなく専用命令 (CAR/CDR/CONS) へ。


def lookup(name, env):
    for i, frame in enumerate(env):
        for j, var in enumerate(frame):
            if var == name:
                return (i, j)
    raise NameError(f"unbound variable: {name}")


def compile_expr(expr, env, code):
    """expr をコンパイルし、code の前に置いた命令列を返す。"""
    if isinstance(expr, int) and not isinstance(expr, bool):
        return [('LDC', expr)] + code
    if isinstance(expr, str):
        return [('LD', lookup(expr, env))] + code
    if not isinstance(expr, list) or not expr:
        raise SyntaxError(f"bad expr: {expr!r}")
    head = expr[0]
    if head == 'quote':
        return [('LDC', expr[1])] + code
    if head == 'if':
        _, c, t, e = expr
        ct = compile_expr(t, env, [('JOIN',)])
        cf = compile_expr(e, env, [('JOIN',)])
        return compile_expr(c, env, [('SEL', ct, cf)] + code)
    if head == 'lambda':
        _, params, body = expr
        body_code = compile_expr(body, [params] + env, [('RTN',)])
        return [('LDF', body_code)] + code
    if head == 'let':
        _, bindings, body = expr
        names = [b[0] for b in bindings]
        vals = [b[1] for b in bindings]
        # ((lambda names body) v...) へ desugar
        return compile_expr([[ 'lambda', names, body ]] + vals, env, code)
    if head == 'letrec':
        _, bindings, body = expr
        names = [b[0] for b in bindings]
        vals = [b[1] for b in bindings]
        # DUM; LDF 本体関数; LDC NIL; 束縛値...; CONS...; RAP。
        # 束縛値と本体は、名前のフレームが先頭に来る環境でコンパイル
        # する（実行時には DUM が置いた空フレームがその位置に来て、
        # RAP が中身を束縛値の列で埋める）。
        rec_env = [names] + env
        body_code = compile_expr(body, rec_env, [('RTN',)])
        # 実行順は DUM; 引数リスト構築; LDF 本体; RAP（RAP は AP と
        # 同じく「上がクロージャ、下が引数リスト」の並びで受ける）。
        c = [('RAP',)] + code
        c = [('LDF', body_code)] + c
        # 引数リストの構築は通常の適用と同じ向き（前に足していく
        # ので、実行順は逆向きになり、リストは名前の順に並ぶ）。
        for v in vals:
            c = compile_expr(v, rec_env, [('CONS',)] + c)
        c = [('LDC', NIL)] + c
        return [('DUM',)] + c
    # 関数適用: 引数を逆順に cons でリスト化し、最後に関数を積んで AP
    args = expr[1:]
    fn = expr[0]
    if isinstance(fn, str) and fn in ('car', 'cdr') and len(args) == 1:
        c = [(fn.upper(),)] + code
        for a in args:
            c = compile_expr(a, env, c)
        return c
    if isinstance(fn, str) and fn == 'cons' and len(args) == 2:
        c = [('CONS',)] + code
        for a in args:
            c = compile_expr(a, env, c)
        return c
    if isinstance(fn, str) and fn in PRIMS and len(args) in (1, 2):
        # プリミティブは専用命令へ（引数は左から順に積む）
        return _prim_compile(fn, args, env, code)
    # 実行順は: LDC NIL; a_n; CONS; …; a_1; CONS; fn; AP。
    # compile_expr は前に足すので、末尾から組み立てる。
    c = compile_expr(fn, env, [('AP',)] + code)
    for a in args:
        c = compile_expr(a, env, [('CONS',)] + c)
    return [('LDC', NIL)] + c


def _prim_compile(fn, args, env, code):
    # 実行順は a_n … a_1 の順に積み、a_1 が top に来る。
    # PRIM は top から pop するので vals[0] が第1引数になる。
    c = [('PRIM', PRIMS[fn], len(args))] + code
    for a in args:
        c = compile_expr(a, env, c)
    return c


# ------------------------------------------------------- SECD マシン
class SECD:
    def __init__(self, code):
        self.s = []       # スタック（先頭が top）
        self.e = []       # 環境：フレームのリスト
        self.c = list(code)
        self.d = []       # ダンプ：(s, e, c) の退避列
        self.counts = {}  # 命令ごとの遷移回数
        self.ld_hops = []  # LD のフレーム段数 i の記録

    def step(self):
        instr = self.c.pop(0)
        op = instr[0]
        self.counts[op] = self.counts.get(op, 0) + 1
        if op == 'LDC':
            self.s.insert(0, instr[1])
        elif op == 'LD':
            i, j = instr[1]
            self.ld_hops.append(i)
            self.s.insert(0, self.e[i][j])
        elif op == 'LDF':
            self.s.insert(0, ('closure', instr[1], self.e))
        elif op == 'DUM':
            # 空のフレームを E の先頭に置く。フレームはリストのまま
            # 共有され、後の RAP が中身を書き換える（rplaca 相当）。
            self.e = [[]] + self.e
        elif op == 'RAP':
            closure = self.s.pop(0)
            args = self.s.pop(0)
            code, env = closure[1], closure[2]
            frame = []
            while isinstance(args, list):
                frame.append(args[0])
                args = args[1]
            # env の先頭が DUM の置いた空フレームのはず。新しい
            # フレームを作らず、中身だけを束縛値で置き換える。
            # こうすると束縛値のクロージャ群が同じフレームを
            # 共有し、自分自身（と相互再帰の相方）が見える。
            dummy = env[0]
            dummy[:] = frame
            self.d.append((self.s, self.e, self.c))
            self.s = []
            self.e = env
            self.c = list(code)
        elif op == 'AP':
            closure = self.s.pop(0)
            args = self.s.pop(0)
            code, env = closure[1], closure[2]
            self.d.append((self.s, self.e, self.c))
            self.s = []
            # 引数は cons ペアの連鎖 ([a1, [a2, NIL]]) で来るので
            # フレーム用に平らなリストへ直す。
            frame = []
            while isinstance(args, list):
                frame.append(args[0])
                args = args[1]
            self.e = [frame] + env
            self.c = list(code)
        elif op == 'RTN':
            result = self.s.pop(0)
            s, e, c = self.d.pop()
            self.s = [result] + s
            self.e, self.c = e, c
        elif op == 'SEL':
            cond = self.s.pop(0)
            # SEL は制御列 C だけを退避する（S・E は退避しない。
            # 分岐の計算結果は S に残らなければならない）。
            # D には AP/RTN 用の三つ組と区別できる印をつけて積む。
            self.d.append(('join', self.c))
            self.c = list(instr[1] if is_true(cond) else instr[2])
        elif op == 'JOIN':
            _, c = self.d.pop()
            self.c = c
        elif op == 'CONS':
            # cons セルは [car, cdr] のペア。真のリスト (1 2) は
            # [1, [2, NIL]]、ドットペア (1 . 2) は [1, 2] になる。
            a = self.s.pop(0)
            b = self.s.pop(0)
            self.s.insert(0, [a, b])
        elif op == 'CAR':
            self.s.insert(0, self.s.pop(0)[0])
        elif op == 'CDR':
            self.s.insert(0, self.s.pop(0)[1])
        elif op == 'PRIM':
            _, name, n = instr
            vals = [self.s.pop(0) for _ in range(n)]
            self.s.insert(0, apply_prim(name, vals))
        elif op == 'STOP':
            return False
        else:
            raise ValueError(f"unknown instruction: {instr!r}")
        return True

    def run(self, limit=100000):
        n = 0
        while self.c and n < limit:
            if not self.step():
                break
            n += 1
        if n >= limit:
            raise RuntimeError("step limit exceeded")
        return self.s[0] if self.s else NIL

    def report(self):
        total = sum(self.counts.values())
        lines = [f"  total transitions: {total}"]
        for op, n in sorted(self.counts.items(), key=lambda kv: -kv[1]):
            lines.append(f"  {op}: {n}")
        if self.ld_hops:
            hops = sum(self.ld_hops)
            lines.append(
                f"  LD: {len(self.ld_hops)}回, フレーム辿り合計 {hops}ホップ, "
                f"最大 {max(self.ld_hops)}段")
        return "\n".join(lines)


def apply_prim(name, vals):
    if name == 'ADD':
        return vals[0] + vals[1]
    if name == 'SUB':
        return vals[0] - vals[1]
    if name == 'MUL':
        return vals[0] * vals[1]
    if name == 'DIV':
        return vals[0] // vals[1]
    if name == 'EQ':
        return vals[0] == vals[1]
    if name == 'LT':
        return vals[0] < vals[1]
    if name == 'ATOM':
        return not isinstance(vals[0], list)
    if name == 'NULL?':
        return vals[0] is NIL
    raise ValueError(name)


# ------------------------------------------------------------- テスト
# 正格評価（引数を先に評価する）では素の Y は (x x) を無限に展開する
# ため、eta 展開した Z コンビネータを使う。
Z = ['lambda', ['f'],
     [['lambda', ['x'],
       ['f', ['lambda', ['y'], [['x', 'x'], 'y']]]],
      ['lambda', ['x'],
       ['f', ['lambda', ['y'], [['x', 'x'], 'y']]]]]]

FIB_BODY = ['lambda', ['fib'],
            ['lambda', ['n'],
             ['if', ['=', 'n', 0], 0,
              ['if', ['=', 'n', 1], 1,
               ['+', ['fib', ['-', 'n', 1]],
                     ['fib', ['-', 'n', 2]]]]]]]

FACT_BODY = ['lambda', ['fact'],
             ['lambda', ['n'],
              ['if', ['=', 'n', 0], 1,
               ['*', 'n', ['fact', ['-', 'n', 1]]]]]]

FACT_LAMBDA = ['lambda', ['n'],
               ['if', ['=', 'n', 0], 1,
                ['*', 'n', ['fact', ['-', 'n', 1]]]]]

FIB_LAMBDA = ['lambda', ['n'],
              ['if', ['=', 'n', 0], 0,
               ['if', ['=', 'n', 1], 1,
                ['+', ['fib', ['-', 'n', 1]],
                      ['fib', ['-', 'n', 2]]]]]]

TESTS = [
    ("((lambda (x) (+ x 1)) 41)", [['lambda', ['x'], ['+', 'x', 1]], 41], 42),
    ("(car (cons 1 2))", ['car', ['cons', 1, 2]], 1),
    ("(cdr (cons 1 2))", ['cdr', ['cons', 1, 2]], 2),
    ("(let ((x 3) (y 4)) (* x y))",
     ['let', [['x', 3], ['y', 4]], ['*', 'x', 'y']], 12),
    ("(fact 5) via Z", [[Z, FACT_BODY], 5], 120),
    ("(fib 10) via Z", [[Z, FIB_BODY], 10], 55),
    ("(fact 5) via letrec",
     ['letrec', [['fact', FACT_LAMBDA]], ['fact', 5]], 120),
    ("(fib 10) via letrec",
     ['letrec', [['fib', FIB_LAMBDA]], ['fib', 10]], 55),
    ("(even? 10) via letrec (mutual)",
     ['letrec',
      [['even?', ['lambda', ['n'],
                  ['if', ['=', 'n', 0], 1, ['odd?', ['-', 'n', 1]]]]],
       ['odd?', ['lambda', ['n'],
                 ['if', ['=', 'n', 0], 0, ['even?', ['-', 'n', 1]]]]]],
      ['even?', 10]], 1),
]


def main():
    ok = True
    for name, expr, expected in TESTS:
        code = compile_expr(expr, [], [('STOP',)])
        m = SECD(code)
        got = m.run()
        status = "OK " if got == expected else "FAIL"
        if got != expected:
            ok = False
        print(f"[{status}] {name} => {got} (expected {expected})")
        print(m.report())
    print("ALL OK" if ok else "SOME FAILED")
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
