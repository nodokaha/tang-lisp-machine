; SDW3.LSP - mount (MBR + BPB geometry) and FAT get/set
(define(mnt)(init)(if(null?(rd 0 buf))()(begin(set! pb(g32 buf 454))(if(null?(rd pb buf))()(begin(set! spc(bytes-ref buf 13))(set! fb(+ pb(g16 buf 14)))(set! nf(bytes-ref buf 16))(set! spf(g32 buf 36))(set! db(+ fb(* nf spf)))(set! rcl(g32 buf 44))(set! tot(g32 buf 32))t)))))
(define(clba c)(+ db(*(- c 2)spc)))
(define(fg c)(let((o(* c 4)))(if(null?(rd(+ fb(ash o -9))buf))()(g32 buf(logand o 511)))))
(define(fs c v)(let((o(* c 4)))(let((s(ash o -9))(k(logand o 511)))(if(null?(rd(+ fb s)buf))()(begin(p32 k v)(if(null?(wr(+ fb s)buf))()(if(= nf 2)(wr(+ fb spf s)buf)t)))))))
