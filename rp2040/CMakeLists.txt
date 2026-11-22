cmake_minimum_required(VERSION 3.13)

include(pico_sdk_import.cmake)

project(tanglisp_rp2040 C CXX ASM)
set(CMAKE_C_STANDARD 11)

# TangLisp's eval is deeply recursive C; give it a real stack.
set(PICO_STACK_SIZE 0x8000)

pico_sdk_init()

add_executable(tanglisp_rp2040 lisp_rp2040.c)

# The interpreter ships its own memset/memcpy; keep the compiler from
# turning their loops into calls to themselves (the old RISC-V lesson).
target_compile_options(tanglisp_rp2040 PRIVATE -fno-builtin)

target_link_libraries(tanglisp_rp2040 pico_stdlib)

pico_enable_stdio_usb(tanglisp_rp2040 1)
pico_enable_stdio_uart(tanglisp_rp2040 0)

pico_add_extra_outputs(tanglisp_rp2040)
