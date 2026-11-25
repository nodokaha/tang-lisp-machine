; SYS.LSP - TangLisp standard library (loaded silently at boot,
; after CONFIG.LSP). Plain functions only (this Lisp has no
; macros). List walkers are built on fold + reverse so they run
; in constant stack (tail calls) at any list length.
(define (fold f acc xs) (if (null? xs) acc (fold f (f acc (car xs)) (cdr xs))))
(define (rng a b acc) (if (> a b) acc (rng a (- b 1) (cons b acc))))
(define (range a b) (rng a b ()))
(define (rev2 xs acc) (if (null? xs) acc (rev2 (cdr xs) (cons (car xs) acc))))
(define (reverse xs) (rev2 xs ()))
(define (append a b) (fold (lambda (acc x) (cons x acc)) b (reverse a)))
(define (length xs) (fold (lambda (acc x) (+ acc 1)) 0 xs))
(define (map f xs) (reverse (fold (lambda (acc x) (cons (f x) acc)) () xs)))
(define (filter p xs) (reverse (fold (lambda (acc x) (if (p x) (cons x acc) acc)) () xs)))
(define (nth n xs) (if (= n 0) (car xs) (nth (- n 1) (cdr xs))))
(define (member x xs) (if (null? xs) () (if (eq? x (car xs)) t (member x (cdr xs)))))
(define (min a b) (if (< a b) a b))
(define (max a b) (if (> a b) a b))
(define (abs x) (if (< x 0) (- 0 x) x))
(define (sum xs) (fold + 0 xs))
(define (sys-marker) 777)
