; SDW5.LSP - cluster allocation + directory entry write
(define(alc n from prev)(if(= n 0)()(if(<(clba from)(+ pb tot))(if(=(fg from)0)(begin(fs from 268435455)(if(= prev 0)t(fs prev from))(cons from(alc(- n 1)(+ from 1)from)))(alc n(+ from 1)prev))())))
(define(ewb o n i)(if(= i 11)t(begin(bytes-set! buf(+ o i)(if(null? n)32(car n)))(ewb o(if(null? n)()(cdr n))(+ i 1)))))
(define(ew l o n cl sz)(if(null?(rd l buf))()(begin(ewb o n 0)(bytes-set! buf(+ o 11)32)(bytes-set! buf(+ o 20)(logand(ash cl -16)255))(bytes-set! buf(+ o 21)(logand(ash cl -24)255))(bytes-set! buf(+ o 26)(logand cl 255))(bytes-set! buf(+ o 27)(logand(ash cl -8)255))(p32(+ o 28)sz)(wr l buf))))
