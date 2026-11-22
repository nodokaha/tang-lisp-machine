MEMORY {
  RAM (rwx) : ORIGIN = 0x00000000, LENGTH = 32K
}
SECTIONS {
  .text : {
    *(.text.start)
    *(.text*)
    *(.rodata*)
  } > RAM
  .data : { *(.data*) *(.sdata*) } > RAM
  .bss : {
    __bss_start = .;
    *(.bss*) *(.sbss*) *(COMMON)
    __bss_end = .;
  } > RAM
  _stack_top = ORIGIN(RAM) + LENGTH(RAM);
}
