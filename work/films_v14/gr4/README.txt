GR IV Cinema extraction (films v14, FINDINGS §25).
fwx.py / emux.py: generic GR III / GR IV firmware reader and ImageTuning emulator (from the GR IV cinema session).
They read the RTOS sections <GR_RTOS_DIR>/gr3_rtos.bin and gr4_rtos.bin: decode the two firmware files with dec.py
(writes *_dec.bin) and cut the RTOS section (section_rows 'RTOS', +16 header as in verify_slots: dec[0x10870:...]).
g4curves.py: GR IV curve composite 0x5391E340 captured (mix r0/r1 from Color Tone ctx+0x60 = SI+0x7A6).
cinema_fit.py: writes ../fits/cinema_yellow.json and cinema_green.json.
