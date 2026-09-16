ENTRY(warning_hook)
SECTIONS {
  . = 0;
  .text : { *(.text*) *(.rodata*) }
  /DISCARD/ : { *(.ARM.exidx*) *(.ARM.extab*) *(.comment*) *(.note*) }
}
