; SDW4.LSP - root directory scan + cluster chain free
(define fsl 0)
(define fso 0)
(define(dnm b o n)(if(null? n)t(if(=(bytes-ref b o)(car n))(dnm b(+ o 1)(cdr n))())))
(define(dsec l n i)(if(= i 16)()(let((o(* i 32)))(if(=(bytes-ref buf o)0)(list 0 l o)(if(=(bytes-ref buf o)229)(begin(if(= fsl 0)(begin(set! fsl l)(set! fso o))t)(dsec l n(+ i 1)))(if(=(bytes-ref buf(+ o 11))15)(dsec l n(+ i 1))(if(not(=(logand(bytes-ref buf(+ o 11))24)0))(dsec l n(+ i 1))(if(dnm buf o n)(list 1 l o(logior(ash(g16 buf(+ o 20))16)(g16 buf(+ o 26)))(g32 buf(+ o 28)))(dsec l n(+ i 1))))))))))
(define(dclu c n s)(if(< s spc)(if(null?(rd(+(clba c)s)buf))()(let((r(dsec(+(clba c)s)n 0)))(if(null? r)(dclu c n(+ s 1))r)))(let((nx(fg c)))(if(< nx 268435448)(dclu nx n 0)(if(= fsl 0)()(list 0 fsl fso))))))
(define(dscan n)(set! fsl 0)(dclu rcl n 0))
(define(fch c)(if(< c 268435448)(let((x(fg c)))(fs c 0)(fch x))t))
