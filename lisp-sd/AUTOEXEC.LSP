; TangLisp AUTOEXEC -- loaded from SD at boot
(define (fib n) (if (< n 2) n (+ (fib (- n 1)) (fib (- n 2)))))
(print (fib 10))
(define (count n acc) (if (= n 0) acc (count (- n 1) (+ acc 1))))
(print (count 2000 0))
(+ 40 2)
