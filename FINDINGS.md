# Ricoh GR III fw 2.10 — image pipeline & film-filter findings

Research notes, in the order the work was done (2026-10-07 .. 2026-10-12): static analysis and Unicorn emulation of
the RTOS, plus camera tests where a section says so. Section headers carry each build's status; later sections
correct earlier ones where noted.

## Status (2026-10-12)

**Latest build: films v33b** (§53) = v33 (§52) with Sony FL refitted from a black-box model of the a7C II's own FL
rendering. Neither v33 nor v33b is camera-tested yet.

| Build | What changed | § | Camera |
| --- | --- | --- | --- |
| v16 | hue sectors (MultiAxial) for every film, RAW development with films | 33-34 | hue chart tested (§33b) |
| v17 | aspect 5:4 / XPan (first try) | 35 | never flashed, set aside |
| v18 | Classic Chrome in the Vivid slot, RAW-dev sliders for appended films | 36 | - |
| v19 | RAW NR on/off from the High-ISO NR menu | 37 | superseded by v20 |
| v20 | High-ISO NR menu picks RAW NR threshold + JPEG NR | 38 | tested (§38a): RAW NR works, JPEG remap lost at power-on |
| v21 | RAW NR only from ISO 5000, JPEG NR stock | 39 | - |
| v22-v22g | Sony FL (Adobe A7 IV / A7C II profile) replaces Gold 200; box icons | 40 | FL chart comparison (§40b) |
| v23 | RTOS grown by 64 KB (extension), Gold 200 back | 42a | boots, extension code runs (§42b) |
| v24 / v25 | every film appended, data in the extension; five more films | 42b-c | - |
| v26 | separate sliders per film, safe return to stock (FILMDATA.bin) | 44a | - |
| v27 / v28 | Grain for films, playback info, RAW-dev values per film | 45-46 | grain recorded but not applied (§47) |
| v29 | effect-stage gate opened for films | 47 | grain visible (§48) |
| v30 | Grain item in RAW development | 48 | - |
| v31 | 4:3 / 16:9 | 50 | never flashed |
| v32 | aspect 3:2 / 4:3 / 5:4 / 65:24 | 51 | wrong live-view ratio + flicker (§52): **do not flash** |
| v33 | open-gate live view with dimmed crop frame (GR4-XPanUnlock style) | 52 | not yet |
| v33b | v33 + Sony FL from the a7C II black-box model | 53 | not yet |

Before flashing stock or an older build: Image Control on a stock mode (shooting, C1/C2/U-modes and movie), Aspect
Ratio 3:2. Stock firmware with a saved film tone reads past its record table (§44). There is one firmware bank, so a
build that does not boot has no automatic fallback (§42).

Open: AF debug probe not run (§49); live-view framing of v33 and the playback / RAW-dev screens of v27-v30 only
emulated; FILMDATA.bin on the real file system (§44a); Sony FL v33b vs the a7C II on real scenes (§53).

**Not in this repository:** firmware images, photos and calibration files; data derived from Adobe DNG profiles (the
v22-v33 Sony FL fits), from Leica (Leica Eternal), maker logos and box art (§40d-f), and GR IV firmware tables. The
builders and scripts after v16 are not published yet; the sections describe what they do. The a7C II work behind §53
is in `sony/` (`A7C2_FINDINGS.md`, `sonysim.py`).

## 1. Input and tooling

- Firmware: `fwdc239b.bin` (official update file), GR III, version 2.10.21.27, SHA-256 `d6a3c9c288d784080e7b283222ecdd8752adfeed6faa36dab44f73115354bfd4`. All addresses below apply to this file only.
- Container format = same family as GR IV; `gr-custom-tool/gr4_editor/codec` decodes it (2430 frames, decoded 0x38F3AF4 bytes).
  - Project id 0x24C (GR IV is 0x27C), 14 sections incl. extra `FDRVPARA`, no metadata records → the GR IV editor refuses it (hard-coded to GR IV 1.11.10.7 SHA). Its public release also deliberately excludes the filter feature.
- Decoded sections: BOOTPARA, DRAMPARA, PARTPARA, M0, BOOT, RTOS @0x10860 (payload +16), LINUX, INITFS, SRIC, CPU, SHELLCMD, ICONBIN, FDRVPARA, RES (DF_EX.bin / DF_IP.bin / DF_ID_S.bin = DSP code for digital filters, not tables).
- RTOS: ARM mode, base 0x53000000. Initialized data copied at boot from ROM 0x5407B540 → RAM 0x55000000 (len 0x3A080). Patch RAM-addressed data at `file = addr - 0x55000000 + 0x5407B540`.
- Functions start with `mov ip, sp`; call there (not at the `push`) when emulating.
- Tools in this folder: `fw.py` (xrefs/disasm), `emu.py` (Unicorn harness), `run_tuning.py` (runs ImageTuningStill::Make), `diffmodes.py`, `sens.py`, `gr3patch.py` (PoC patch builder). See README.md.

## 2. Still pipeline (BE still recipe steps)

`PRO_SRO → B2B → B2B_B2R_R2Y → CNR → DIGITAL_FILTER → RESIZE(IIP) → JPEG_ENC`

- R2Y core blocks (from register-dump strings): CNTL, OFG (WB gain/offset), CCA0 (3×3 matrix CC0K + Y-dependent CC0YB*), BTC/TC (tone control), GAM (gamma), CCA1, YNR, edge enhancement, YBCRV, CLPF, CSP (RGB→YCbCr).
- IIP engine (DIGITAL_FILTER / resize): 1D loader, Affine, FreeRect, Blend, CSC, GPC, LUT units A–F (1D, with pre-calc), MinMax, Monitor, SPF, Store. **No 3D LUT hardware anywhere.**
- DIGITAL_FILTER dispatcher 0x535032B8: 6 ops (Effect 0x53680DBC fed by 0x5350304C, 0x536793C0, Demoire 0x53685D24, 0x53682A58, 0x5368AA9C, 0x53682004). Effect op reads only SI+0x793..0x796 (shading/clarity/grain-type params); no mode-dependent branch.

## 3. ImageTuning (R2Y parameter generation)

- `ImageDevelopmentPipeService::MakeImageTuningParameter` 0x5365C144 → virtual Make (vtable+0x1C).
- Vtables: ImageTuning base 0x53DBD240; Still 0x53DBD8A0 (Make 0x536DD8F0); LiveView 0x53DBD938 (Make 0x536DDECC); init methods 0x536DA1FC (creates sub-tunings) and 0x536DA62C (buffers/defaults).
- Sub-tuning objects (ImageTuning+off, Make fn): +0x154 Interpolation 0x536DECB4, +0x158 ColorMatrix 0x536DF3D4 (calc 0x536DEECC), +0x15C MultiAxial 0x536E4470 (calc 0x536DF484, write 0x536DF55C), +0x160 LumaNr, +0x164 YCbCrMatrix 0x536E4760, +0x168 ColorReference 0x536E4C1C, +0x16C CoordinateScale, +0x170 ColorLpf, +0x174 EdgeEnhancement, +0x178 YCbCrOperation 0x536E77DC (calc 0x536E73D0), +0x17C Gamma 0x536E9000 (calc 0x536E8FBC, write 0x536E7A24), +0x180 ToneControl 0x536E9D1C (calc 0x536E9BD8, write 0x536E91A8), +0x184 ResizeEdge, +0x188 Suppre, +0x18C Reduce.
- Context fill: 0x536DD270, 0x536DB130, 0x536DC0F4 (+ 0x536DB7D8 param pass-through). Input `info`: +0x82AC stage (0 LV, 1/2 still), +0x82D0 ShootingInfo ptr (still uses SI+0x71248). R2Y output block = info+0x120.
- LiveView Make calls the same sub-tunings (gated by dirty flags obj+4..+0x12) → **changes show in live view** (confirmed by emulation).

## 4. Mode identification (confirmed)

- Internal tone = ShootingInfo+0x77C. EXIF Pentax ImageTone 256+n → 11+n (table 0x53D2D920). UI code (e.g. GetDefaultValueSaturation 0x532C34EC) switches on tone-11.

| Tone | Mode | Record slot |
|---|---|---|
| 11 | Standard | 11 |
| 12 | Vivid | 12 |
| 13 | Monotone | 13 |
| 14 | Soft Monotone | 14 |
| 15 | Hard Monotone | 15 |
| 16 | Hi-Contrast B&W | 16 |
| 17 | Positive Film | 17 |
| 18 | Bleach Bypass | 18; SI+0x786=2 → 22, =3 → 23 |
| 19 | Retro | 19 |
| 20 | HDR Tone | 20; SI+0x788=1/2 → 24 (mono) |
| 21 | Cross Process | 21 (SI+0x797 = preset 0/1/2) |
| 22 | Negative Film | 25 |

- Slots 0–10 are unreachable legacy looks with full data (likely Pentax custom images; by saturation: 0 identity, 1 = Vivid matrix, 3 ~1.3× "landscape", 4 green-boost "vibrant", 5 ~2× "radiant", 6 ~0.75× "muted", 7 ~0.95, 8 ~0.55 hue-shifted, 10 mono). Names unconfirmed.

## 5. Per-mode look record (confirmed)

- Pointer table RAM **0x55018D94**[slot] → 0x54-byte record of 17 pointers.
- Other per-tone tables in ctx fill: 0x55018CF0 (all same), 0x55018E4C (mono/variant flag-ish), ColorRef uses 0x53DC5750 when tone==9.
- Record fields:
  - f0: camera base matrix (s16)
  - **f1: look matrix, 9 × s16 Q13 (0x2000 = 1.0), row-major, rows = out R,G,B, rows sum to 1.0**
  - f2: array of matrices indexed by saturation step (mono records: mono conversion)
  - f3, f4: extra (f4 → luma coeffs 77/150/29)
  - f7, f11–f14: YCbCrOperation — **toning** (Cb/Cr offset tables indexed by toning param ctx+0x60)
  - f15/f16: ToneControl 4 offsets (only Retro nonzero: (-32,0,120,0)/(-16,0,60,0))
- Final CCA0 = A(saturation) · Look · CameraMatrix, then global saturation scale, clamped 12-bit signed, Q8 (row sum 256). Example Standard `[436,-184,4,-48,400,-96,1,-104,359]`.
- Look matrix addresses (single-referenced unless noted): Std/HDR/Cross share 0x53DC2754; Vivid 0x53DC26DC; Positive 0x53DC272C; Bleach 0x53DC2474 (var 0x53DC26F0, 0x53DC24C4); Retro 0x53DC2818; Negative 0x53DC2AD0; Mono+slot24 share 0x53DC2A94.

## 6. What actually differs between modes (emulated, neutral params = 4)

- Standard vs Vivid/Positive/Negative/Retro/Bleach: **only the color matrix** (+toning tables, Retro offsets). Gamma/tone curves identical. Mono modes: matrix with identical rows + YCbCr chroma.
- Per-mode tone curves exist only for:
  - **Cross Process**: per-channel R/G/B curves composited into gamma (0x536E87A8, gated by ctx+0x9B = SI+0x38A98≠0). Curve library RAM **0x55037604** = 12 × 256-entry u16 (14-bit) curves at ROM 0x53EFB0E4… (0x200 each). Presets: sub0 = R3,G4,B5; sub1 = R6,G7,B8; sub2 = R9,G10,B11. Curves 0–2 unused. Selector object 0x5536DAB8 (+0xE/+0xF/+0x10 = R/G/B index); getter 0x536EEDF0.
  - **Hi-Contrast B&W**: DigitalFilterGammaCoordinator (singleton 0x5536DBFC, RTone/GTone/BTone 256-entry) via 0x536F0290 when tone==16.
- Param mapping (SI offsets): 0x77D saturation → matrix; 0x77E hue → YCbCr matrix; 0x780 contrast, 0x781 highlight contrast, 0x782 shadow contrast → gamma; 0x784.. sharpness etc.; 0x793–0x796 → DIGITAL_FILTER effect.
- Gamma write: 4 tables × 0x800 bytes at out+0x2568/0x2D68/0x3568/0x3D68 (R,G,B,Y — packed register format) + 4 × 0x200 at +0x4768…; patching curve 3 changes table 0 (R) and table 3 (Y) only.
- Other gamma data: DR/brightness-blend curves table RAM 0x550204E0 (31 curves, 7 levels); "BasicGammaTableNatural/Reversal" are copied into ShootingInfo for metadata, not imaging. ToneControl is scene-adaptive (histogram-based).

## 7. MultiAxial (hue-area color correction) — partially confirmed

- Calc 0x536DF484, write 0x536DF55C → output info+0x120+0x100…0x6FF.
- Source set struct ROM 0x53DC2BA0: [0] 16 × u16 boundaries (0x53DC3198), [1] 20 × 4-bit area selectors (0x53DC2BB8), [2] RAM 0x55019828 → table 0x53DC31D0 = **540 int32 = 60 × 3×3 matrices (Q10)**, [3]→ 10-bit table, [4] 12-bit thresholds, [5] RGB→YCbCr coeffs (77,150,29,-43,-85,128,128,-107,-21…).
- Table entry i maps linearly to 12-bit register fields (6 blocks × 90 entries, 0x100 bytes per block).
- **GR III ships boundaries and selectors all zero → inactive.** Only block 0 matrix 0 non-identity.
- Geometry (how boundaries/selectors partition Cb/Cr hue) is **unconfirmed**; no public docs (Socionext M10V/SC2000 register manual is NDA). Closest public description: axis-based hue/saturation remapping patents (US7907148, US7903178), not confirmed as Fujitsu/Ricoh. Needs camera test with marker values.

## 8. Firmware update acceptance (static)

- FwDecoder (0x5362BD44 header, 0x5362BEA8 decoded sum, 0x5362BF4C decode): checks header project (0x30), [0x78]==proj|proj<<16, [0x7C]==0xA55A5AA5, footer project/marker/fw type, container additive sum32==0, decoded size, **decoded sum32==0** (last decoded word is the fixer).
- Version check 0x536284E4: (major<<16|minor) of file **≥** current → same 2.10 accepted.
- No signature/RSA found in RTOS updater; BOOT loader strings only report load errors.
- Special SD files: C:\FWBYPASS, C:\FWDEL.BIN, C:\NOWAIT, C:\NOOFF.BIN, C:\KBCHG.BIN.

## 9. Proof of concept (offline)

- `gr3patch.py` patches Retro's look matrix (0x53DC2818) with a warm matrix, repacks with `_repack_frames` (2428/2430 stock frames reused, 30,415,816 bytes).
- Verified: all updater checks pass; re-decode differs only in the 18 matrix bytes + checksum word; emulated Retro CCA0 changes `[261,-24,19,…]` → `[492,-266,30,…]` (still & live view), Standard unchanged.
- Test file was written to the session scratchpad (`out/fwdc239b_retro_test.bin`); regenerate with `gr3patch.py` if needed.

## 10. Other useful facts

- SHELLCMD section: ~585 engineering commands incl. CAP_REG_B2Y, CAP_REG_IIP, CAP_DumpImageMap, CAP_Lut, SYS_md/SYS_mm, SYS_script, lcmd (Linux shell bridge). Access path on GR III unverified.
- C:\SYSPARAM.TXT (DebugInfoOfferer 0x536555E0) = sensor/engineering debug flags only (DUMP_STILL_REGISTER, DUMP_B2B_REGISTER…), nothing color.
- Engineering/TTL interfaces documented for GR IV in the ricoh-gr4-firmware-analysis-and-feature-expansion project.

## 11. How to build a LUT-style film filter

No 3D LUT → decompose a target LUT into:
1. **Look matrix** (record f1) — data patch, confirmed.
2. **Per-channel 1D curves** — replace a Cross Process preset's 3 curves in the 12-curve library (data patch, confirmed); or small code patch to enable the RGB-curve path for another mode.
3. **Toning tables** (f11–f14) for split-tone highlights/shadows.
4. **MultiAxial** hue-area matrices for selective color — after its geometry is learned on camera.

## 12. Open items / next steps

(The 2026-10-07 list. Done later: 1 §14a, 2 §30a-b, 3 §22h / §33b, 4 §13, 6 §33. Current open items: Status at the top.)


1. Flash test: does the camera accept/boot a patched file? (Keep stock fwdc239b.bin to reflash.)
2. MultiAxial geometry: flash a variant with marker boundaries/matrices, shoot a color chart.
3. RAW+JPG validation: same scene per mode (tripod, M mode, Daylight WB, ISO 200, all params 0, DR/Clarity/Shading off; plus Standard Contrast+2 and Saturation+2). Develop DNG through the extracted model and compare to camera JPG.
4. ~~Tool: `.cube` → matrix + curves fitter~~ done, see §13.
5. Confirm the gamma-index exposure assumption (§13) with a RAW+JPG pair; refit if mid gray isn't at index ~7.8.
6. Yellow→orange hue shift of Portra needs MultiAxial (after its geometry is known).

## 13. Portra 400 via spektrafilm (built offline, 2026-10-07)

Source: spektrafilm (v0.3.4). `spektrafilm-lut build --film kodak_portra_400 --print kodak_portra_endura --input vlog --output srgb --resolution 33` (+ a `fujifilm_crystal_archive_typeii` print variant). LUTs are CC BY-SA 4.0 + spektrafilm LUT license → credit spektrafilm, share alike, no resale.

**Cross Process composite (0x536E8668, confirmed):** when ctx+0x9B≠0 each channel's 256-entry gamma becomes `out_c[i] = Curve_c(Base[i])` (index Base>>6, 6-bit lerp, entries ≥255 use the last value); Y table = (77R+150G+29B)>>8 of the composites. Base = Standard 256-entry 14-bit gamma (dumped: `work/base_gamma_std.npy`, identical for Std/Cross at neutral params).

**Model used by `cube_fit.py`:** `code_c = Curve_c(Base(K·(M·L)_c))/16384`, L = linear sRGB after camera matrix. **Assumption:** Base index domain is linear and 18% gray lands at index ≈7.8 (Standard → sRGB ≈0.46), K = 7.8/0.18. Needs RAW+JPG confirmation.

**Fit (shared M, 3 presets, gray weighted as near-hard constraint, skin 3×):**
| Cross preset (SI+0x797) | Target | Chart ΔE2000 mean / max | Standard vs target |
|---|---|---|---|
| 0 | Portra 400 → Portra Endura | 3.0 / 11.5 | 5.7 |
| 1 | same, +1 EV (overexposed Portra) | 3.3 / 10.2 | 12.2 |
| 2 | Portra 400 → Fuji Crystal Archive | 2.3 / 7.3 | 5.3 |
Grays within ~1/255. Residual errors are yellows/oranges (Portra rotates yellow toward orange) — not expressible with matrix+per-channel curves; MultiAxial territory.
M = [[0.786,0.246,-0.032],[-0.014,0.862,0.152],[-0.007,0.039,0.968]].

**Patch (`make_film.py`, data only):** Std/HDR/Cross share record 0x5501900C and matrix 0x53DC2754, so: copy that record over unreachable legacy record of slot 2 (0x5501939C), keep its f1 → 0x53DC2A54 (single-ref), write M there (Q13), set RECORDS[21] = 0x5501939C; overwrite curves 3–11 (each ROM curve pointer single-referenced from the library table). Note: a second record table at RAM 0x55037634 (used by 0x536EFAA8, caller unknown) also lists slot-2's record at its index 2; Cross/HDR aren't in that table.

**Verified offline (`verify_film.py`):** container & decoded sum32 = 0, only RTOS bytes changed, Standard and HDR R2Y output byte-identical to stock, Cross presets 0–2 composite curves = fitted curves (±1/16384), CCA0 `[436,-184,4,-48,400,-96,1,-104,359]` → `[338,-85,3,-43,305,-6,12,-120,364]`.

Output: `work/portra400/fwdc239b_portra400.bin` (SHA-256 95dc0989…1d79d3), fit `portra_fit.json`, preview `portra_preview_small.jpg` (columns: Standard model | camera-achievable fit | spektrafilm target; rows = presets 0/1/2). Menu still says "Cross Process" (UI strings not patched). **Not flashed.**

The Portra build in §13 was flashed and works on the camera (2026-10-07).

## 14. Four film modes replacing Cross Process / Vivid / Retro / HDR Tone (built offline, 2026-10-08)

`make_films.py` (+ `make_icons.py`, `make_names.py`), check with `verify_films.py`. Output `work/films/fwdc239b_films.bin` (SHA-256 25ca2899…97b3ea), previews `charts.png` (Standard | fit | target), `icons.png`.

| Menu slot (tone) | Film (spektrafilm v0.3.4, print) | Curve set (selector) | Record | Chart ΔE2000 fit / Standard |
|---|---|---|---|---|
| Cross Process (21) | Portra 400, Portra Endura | 2: R3,G4,B5 | legacy slot 2 0x5501939C | 2.9 / 5.7 |
| Vivid (12) | Ektar 100, Portra Endura | 4: R9,G10,B11 | own 0x550196D8 | 3.4 / 6.2 |
| Retro (19) | Gold 200, Portra Endura | 3: R6,G7,B8 | own 0x55019108 | 2.7 / 5.2 |
| HDR Tone (20, also slot 24) | Pro 400H, Crystal Archive | 3 (shared with Retro, matrix-only fit) | legacy slot 1 0x55019060 | 3.3 / 4.3 |

**Curve-set selector.** SI+0x38A98 (→ ctx+0x9B) maps via table 0x53DBD19C (`[8,0,1,2,3,…]`) to a Cross mode for 0x536EF140: value 2/3/4 = Cross preset 0/1/2 with fixed curve indices; value 1 = Cross "random" (0x536EF618, rand()%6 / %9 → not deterministic, still and LV differ); 5..8 copy a saved set from SI+0x38A9A via 0x536EEE30. So only three independent curve sets exist; the composite works for any tone once the selector is non-zero.

**Code patches (equal size):** 0x536DD450 `ldrne`→`ldr`, 0x536DD454 `beq`→`b` into 0x536DD4B8, where the old Cross-preset chain is replaced by `mov r2,#0; cmp r1,#tone; moveq r2,#sel …; strb r2,[r3,#0xa98]` for tones 12/19/20/21. 0x536DBEB4 `ldrb sb,[r3,#0x788]` → `mov sb,#0` (HDR Tone passes HDR intensity 0 at ctx+0x1F0, as Standard does). 0x536DC27C `beq` → `nop` (HDR always record slot 20; the SI+0x788=1/2 branch chose mono slot 24). ImageTuningStill::Make output for HDR vs Standard differed **only** in ctx+0x1F0, i.e. the HDR effect runs in another stage that I have not located; whether intensity 0 switches it off is unconfirmed until tested on camera.

**Icons:** tone→icon 0x532935DC: Vivid 0x224, Retro 0x164, HDR 0x15F, Cross 0x32 (each 40×40, single descriptor, unique pixels). Redrawn on the Positive Film film-strip frame (0xE8) with labels P400 / E100 / G200 / 400H.

**Names:** string table 0x55002BAC[21 langs][0x311]; entry = {u8 chars incl. NUL, u8 1, u16 0, u32 → UTF-16LE}. Tone→string id 0x532922B4: Vivid 0x10C, Retro 0x114, HDR 0x115, Cross 0x116. New name written over the longest translation of the id; all 21 language entries repointed (Portra 400 / Ektar 100 / Gold 200 / Pro 400H).

**Verified offline:** sums 0, only RTOS+ICONBIN changed, Standard/Monotone/Positive/Bleach/Negative R2Y byte-identical to stock (still and LV), each film mode's composite = fitted curves (±1/16384) in still and LV, names/icons read back. Cross presets 0–2 now all give Portra 400. Not flashed.

### 14a. Camera test 1 (`../photo-test1`, 2026-10-08) and v2

Same scene, ISO 200, Daylight WB, 1/2000 f/3.2, all sub-settings 0; R0011725 Standard, 21 Cross→Portra, 24 Vivid→Ektar, 23 Retro→Gold, 22 HDR→400H. DNG developed linear (rawpy, camera WB, sRGB primaries), JPG aligned by ECC, 375×250 px. Standard fitted as JPG = BaseGamma(A·lin) (dE 3.4 mean; residual = in-camera lens shading + shadow lift). Then each film JPG vs my model with the same A:

| Shot | camera vs model ΔE | camera vs film target ΔE | luma residual corners / highlights |
|---|---|---|---|
| Standard | 3.4 | — | +15 / −6 (shading corr., baseline) |
| Portra (Cross) | 3.2 | 4.0 | same as Standard |
| Ektar (Vivid) | 3.1 | 4.0 | same as Standard |
| Gold (Retro) | 8.1 | 8.7 | −50 / −37: **vignette + flattened highlights** |
| 400H (HDR) | 5.5 | 6.0 | shadows +15, highlights −17: **HDR local tone mapping still on** |

Portra/Ektar behave exactly as modelled (residual identical to Standard's) → curve composite, matrices and the exposure assumption (scene median at base-gamma index 8.2 under AE, assumed mid gray 7.8) hold; no refit needed. Retro and HDR have effects outside ImageTuningStill::Make (emulated Make output differs from Standard only in matrix/curves plus Retro's ctx+0x1F0 toning=4 and ctx+0x1FC=4).
v2 (`work/films_v2/fwdc239b.bin`, SHA-256 7528690b…edbeb699) adds: HDR SI+0x796/ctx+0x1FA forced 0; 0x535131C0 local-process gate for HDR = Standard's (was SI+0x796≠0); Retro ctx+0x1FC 4→0. Both are best guesses — needs camera test 2. Fallback if they don't work: put Gold 200 / Pro 400H on Positive Film (17) / Bleach Bypass (18), which Make treats like Standard.

### 14b. Camera test 2 (`../photo-test2`, v2 firmware) — Retro/HDR fixed

Indoor scene, ISO 200, Daylight WB. Standard R0011736 (1/200 f/2.8, **DR expansion Off**, BaselineExposure −0.51); films 1/20–1/15 f/8 with DR expansion On (BaselineExposure +0.49, i.e. raw 1 EV under + digital gain) — corrected by ×2^1.0 on the linear data. A monitor showing video is in frame.

| Shot | camera vs model ΔE | camera vs film target ΔE | luma residual corners |
|---|---|---|---|
| Standard (fit) | 2.5 | — | +13 (lens shading corr.) |
| Portra (Cross) R0011740 | 3.3 | 3.8 | +5 |
| Ektar (Vivid) R0011737 | 2.4 | 3.3 | +7 |
| Gold (Retro) R0011738 | 2.6 | 3.1 | +7 (was −50 in test 1) |
| 400H (HDR) R0011739 | 2.6 | 3.7 | +8 (no local tone mapping) |

Retro's vignette/highlight flattening and HDR's local tone mapping are gone; all four slots now match the model like Standard does. So ctx+0x1FC=4 drove Retro's effect, and SI+0x796 / the 0x535131C0 gate drove HDR's. v2 is the build to use.

## 15. MultiAxial probe, round 1 (built 2026-10-08, not yet shot)

Register mapping (emulated, halfword index in info): YCbCr coeffs 208–216; 16 boundaries 224–239 (12-bit); 20 selector **bytes** (4 bits used) → 240–247 packed 5 per 2 halfwords; matrices 272.. (12-bit signed Q10, ±2.0, value 4096 wraps); control block (set[4] = selector block + 0x14): [0] 6-bit field at byte 0xA00 (hw 1424), [1..8] 12-bit thresholds 1428–1435 (stock 4095), [9..20] 1436–1450 (32, 0,0,21,62,0,1,2,7,0,640,1280); set[3] object → +0x10 → **360** × 10-bit table (stock all 0) → hw 1040…; per-tone set table 0x55018CF0 (Negative = slot 25). Calc copies from ctx instead when ctx+0x94≠0 (not seen in emulation).
Stock matrix 0 = (420,76,16 / 38,458,16 / 38,76,398) = 0.5·(0.75·I + 0.25·luma) in Q10 — would halve brightness if used, so the stock config either bypasses the block or never selects matrix 0.

Probe `make_ma_probe.py` → `work/ma_probe1/fwdc239b.bin` (SHA-256 53af0563…a35b41), checked by `verify_ma_probe.py`. All 60 matrices = gain·I with gain LEVELS[m % 8] = 0.85…0.18 (bypass = 1.0); data in the Cross curve ROM area (Cross curves disabled). Probe modes all use the Standard look record (+ HDR/Retro extras off), so vs. a Standard shot the only change is MultiAxial:

| Mode | boundaries | selectors | control[0] | thresholds |
|---|---|---|---|---|
| Vivid | i·256 | i (0..15), 0×4 | 0 (stock) | stock |
| Positive | i·256 | i | 1 | stock |
| Negative | i·256 | i | 0x3F | stock |
| Retro | i·256 | all 5 | 0 | stock |
| HDR Tone | i·256+128 | i | 0 | stock |
| Cross | i·256 | i | 0 | 511,1023…4095 |

Chart: `make_hue_chart.py` (36 hues × 6 sat/brightness rows + gray row, corner markers).

### 15a. Probe round 1 result (photo-ma1, R0011749-54, 2026-10-08)
Shot: Standard, Vivid, Negative, Positive, Retro, HDR (no Cross, no closing Standard). Every probe
mode came out identical to Standard: per-patch (36x7) differences <= 3.6/255 in every channel,
mean brightness ratio 1.000-1.008, versus the designed 0.85..0.18 gains. All modes showing the
Standard look confirms the probe firmware was running (stock Negative/Positive/Retro look different).
=> MultiAxial is bypassed for stills regardless of boundaries/selectors/control[0] (0, 1, 0x3F)/
matrices, even though the emulated register image matches the design. The enable must be elsewhere
(a module enable/bypass bit in another register block, or the info+0x120 image is not the one the
still path loads). Next: find who reads info+0x120 MultiAxial registers / the module enable mask.

## 16. MultiAxial probe, round 2 (built 2026-10-08, not yet shot)

Why round 1 did nothing (emulated write trace of the info block, `re/regmap.py` in the session scratchpad):
MultiAxial is part of the **CCA0 register group** at info+0x120, not a separate block.
- byte +0x00 bits 0-1 = **CC0CTL** (2-bit), written by the ColorMatrix writer 0x536DF13C from calc out[0],
  which the calc **hard-codes to 1** (0x536DEF10 `mov r3,#1`) for every mode, still and LV.
- +0x20..0x30 CC0K matrix, +0x40..0x56 Y-dependent blend (CC0YB*), +0x80.. MultiAxial (writer 0x536DF55C).
- The matrix registers are 5 per 0x80 bytes, stride 10 halfwords: matrix m at hw 272 + 64·(m//5) + 10·(m%5).
- info+0x1220 = a second group (CCA1-like, 2-bit ctl at +0x1220 from ColorMatrix out+0x30, stock 0).
Hypothesis: CC0CTL 1 = linear matrix only; 2/3 switch MultiAxial in (instead of / in addition to CC0K).

`make_ma_probe2.py` → `work/ma_probe2/fwdc239b.bin` (SHA-256 99c916af…a01200), checked by `verify_ma_probe2.py` (ALL OK).
- Per-mode CC0CTL via a tag in the probe sets' YCbCr array halfword 9 (stock padding 0) = 0xA500|ctl; MultiAxial Make's
  tail call 0x536E4498 → stub at 0x536DD4B8 (dead Cross-preset code, round-1 patches kept) that rewrites CC0CTL bits 0-1.
- Matrices: m = diag(R,G,B), G = 256·LEVELS[m%10] (1.0 … 0.21), R/G,B/G = TINTS[m//10]; peak 256 ≤ 1.0 in Q8/Q9/Q10.
- Boundaries i·256, selectors i (Cross: all 0).

| Mode | CC0CTL | selectors | control[0] |
|---|---|---|---|
| Vivid | 2 | i | 0 |
| Positive | 3 | i | 0 |
| Negative | 2 | i | 0x3F |
| Retro | 3 | i | 0x3F |
| HDR Tone | 0 | i | 0 |
| Cross | 2 | all 0 | 0 |

### 16a. Probe round 2 result (photo-ma2, R0011755-63, 2026-10-08)
Patch analysis (`ma2/*.py` in the session scratchpad): JPG → base-gamma index, fitted 3×3 vs Standard. RAW patches equal
across shots (<1 %), Standard vs closing Standard identical (index rms 0.05).
- **CC0CTL is a gain on the CC0K output, not a MultiAxial enable**: 0 → ×0.50, 1 → ×1 (stock), 2 → ×2.0, 3 → ×3.9 (clipped).
  Fitted G ≈ diag gain with small off-diagonals; Neg (ctl0 0x3F) = Vivid, Retro (0x3F) = Positive → control[0] no visible effect.
- MultiAxial **is running at stock CC0CTL**, but weakly: zones with selectors = i vs. all-equal selectors give a hue-local
  change (yellow-green..green −2 codes at ×1, −8 at ×2; cyan..magenta +1), the same pattern in round 1 (Vivid/Neg/Pos/HDR vs
  Standard; Retro with all selectors 5 ≈ Standard). The coded matrices (gains 0.2–1.0) do **not** show → they are gated.
  Candidates: the 360-entry per-degree table (stock 0) and/or the thresholds (stock 4095).

## 17. MultiAxial probe, round 3 (built 2026-10-08, not yet shot)
`make_ma_probe3.py` → `work/ma_probe3/fwdc239b.bin` (SHA-256 952bc302…3db7b2b), `verify_ma_probe3.py` ALL OK. Stock CC0CTL,
round-2 matrices, bounds i·256. Hue table = 360 × 384 (int32 source, written as 10-bit) at 0x53EFC198, own object.

| Mode | thresholds | hue table | selectors |
|---|---|---|---|
| Vivid | 0×8 | stock 0 | i |
| Positive | 511…4095 ramp | stock 0 | i |
| Negative | stock 4095 | 384 | i |
| Retro | 0×8 | 384 | i |
| HDR Tone | ramp | 384 | i |
| Cross | 0×8 | 384 | all 0 |

### 17a. First round-3 shoot (photo-ma3, R0011764-72) was taken on round-2 firmware
Per-mode gains reproduce round 2 exactly (Vivid/Neg/Cross ×2.0, Pos/Retro ×3.9, HDR ×0.51; Vivid≈Neg, Pos≈Retro, Vivid vs
Cross green difference ≤8 codes), which the round-3 build cannot produce (CC0CTL 1 in every mode). The SD card held the
round-3 file (SHA 952bc302…, copied 19:13) but the update was evidently not applied. Reshoot needed after flashing.
Quick check after flashing round 3: Vivid must NOT be ~1 stop brighter than Standard.

### 17b. Probe round 3 result (photo-ma3, R0011773-81, 2026-10-08)
Round-3 firmware confirmed running (no gain changes). Every probe mode is within dE2000 0.9 of Standard (Std vs Std2 0.5):
thresholds 0 / ramp / stock × hue table 0 / 384 do **not** let the coded matrices act. All probe modes, Cross with
selectors 0 included, show the same ≤3-code (≤6 for Cross) dip in yellow-green..green → that small effect is probably
not MultiAxial at all (some other non-Standard-mode difference), so §16a's "MA runs weakly" is withdrawn.
=> No field of the MultiAxial set (bounds, selectors, control[0], thresholds, hue table, matrices) and no CC0CTL value
makes MultiAxial act on stills.

## 18. MultiAxial probe, round 4 (built 2026-10-08, not yet shot) — last planned
`make_ma_probe4.py` → `work/ma_probe4/fwdc239b.bin` (SHA-256 feec3736…de33416), `verify_ma_probe4.py`.
Tests an enable bit elsewhere in the CCA0 header (info+0x120..0x13F; only CC0CTL bits 0-1 are ever written): per mode a
32-bit OR mask via the round-2-style stub (tag 0xA500|offset, mask in YCbCr array hw 10-11). MA config: bounds i·256,
selectors i, stock thresholds, hue table 384, coded matrices.

| Mode | header word | OR mask |
|---|---|---|
| Vivid | +0x00 | 0x000000FC |
| Positive | +0x00 | 0x0000FF00 |
| Negative | +0x00 | 0xFFFF0000 |
| Retro | +0x04 | 0xFFFFFFFF |
| HDR Tone | +0x08 | 0xFFFFFFFF |
| Cross | +0x10 | 0xFFFFFFFF |

### 18a. Probe round 4 result (photo-ma4, R0011782-89, 2026-10-08) — MultiAxial investigation closed
All six header-mask modes within dE2000 0.8 of Standard (max 7.7 codes, same small non-Standard-mode green dip as before).
No closing Standard shot; the round-4 build has no visible signature, so "flashed" is assumed from the user's report.
Conclusion after 4 rounds: nothing reachable from the tuning data (MultiAxial set fields, CC0CTL, CCA0 header words
0x00/0x04/0x08/0x10) makes the MultiAxial matrices act on stills. Possible remaining causes (not pursued): an enable in a
register the R2Y driver sets outside the tuning image, or the block absent/fused off on this SoC. Selective hue shifts
must be approximated with look matrix + per-channel curves (§11 items 1-3).

## 19. Films v3: warm-hue weighted refits (built 2026-10-08, offline)
`cube_fit.py --boost W --neutral N` adds `warm_samples` (HSV hue 15–90°, sat 0.35–1, 4.5 stops; weight W × chart total)
and `near_neutral_samples` (±8 % channel spread, 8 stops; N × that) so warm hues get priority without tinting neutrals.
Picks (fits in `work/films_v3/fits/`, chosen with `eval_warm.py` and `work/films_v3/regions.py`):

| Film (slot) | fit | warm-set dE v2→v3 | warm hue error v2→v3 | general dE v2→v3 | test2 scene: neutral / warm / other |
|---|---|---|---|---|---|
| Portra 400 (Cross) | b4 n3 | 4.80→3.38 | +6.3°→+2.5° | 3.10→3.30 | 0.79→1.08 / 5.47→4.17 / 2.53→2.48 |
| Gold 200 (Retro) | b4 n3 | 3.88→3.12 | +3.2°→+0.6° | 3.06→3.24 | 0.74→1.09 / 4.87→3.81 / 2.59→2.53 |
| Ektar 100 (Vivid) | b1 n3 | 5.17→4.59 | +5.8°→+4.1° | 3.54→3.53 | 0.92→0.99 / 5.77→5.26 / 3.01→2.99 |
| Pro 400H (HDR, Gold curves) | b2 n3 matrix-only | 3.59→3.22 | +3.7°→+2.5° | 3.40→3.39 | 2.33→2.52 / 4.61→4.18 / 2.66→2.75 |

(+hue error = rendered more yellow than the spektrafilm target.) Costs: neutrals +0.1–0.3 dE, purples/magentas +1–2 dE on
the chart; skin patches improve. Ektar b2+ tints neutrals badly (2.4), so only b1. Without the neutral set (n0), b4 raised
neutral dE to 1.3.
Build: `make_films.py` → `work/films_v3/fwdc239b.bin` (SHA-256 68821c7d…79bef35), `verify_films.py` ALL OK.
Visual: `work/films_v3/compare_v2_v3_target.jpg` (v2 model | v3 model | target, photo-test2 RAWs), `compare_crop.jpg`.

### 19a. Films v3 on camera (photo-ma5, R0011790-96, hue chart, 2026-10-08)
`work/films_v3/check_ma5.py` (Standard model fitted on this shot: dE 0.63; 252 patches, warm = target C>20, hue 30–100°).

| Film | camera vs v3 model | camera vs target (all / warm) | warm hue err camera | v2 model vs target (all / warm, hue) |
|---|---|---|---|---|
| Ektar 100 | 0.53 | 3.51 / 4.40 | −0.8° | 3.52 / 4.90, +0.9° |
| Gold 200 | 0.54 | 3.11 / 3.11 | −3.5° | 2.96 / 3.89, −1.5° |
| Pro 400H | 0.56 | 2.87 / 2.43 | +1.5° | 2.97 / 2.87, +2.6° |
| Portra 400 | 0.53 | 3.06 / 2.91 | 0.0° | 2.89 / 4.28, +3.6° |

The firmware renders exactly what the v3 model predicts (dE ≈ 0.5). Warm colours improve for all four (Portra the most);
overall chart error is ±0.15 of v2. On this chart Gold lands slightly too orange (−3.5°). (− = more orange than target.)

## 20. Films v4: Pro 400H gets its own curves (built 2026-10-08, offline)
Library curves 0–2 were only used by the Cross "random" preset (unreachable once the selector is forced per tone), so
they now hold Pro 400H's own fitted curves. `make_films.py` code patch at the ctx-fill tail (0x536DD454–0x536DD464 +
0x536DD4B8…): `cmp r1,#20`, then movweq/movwne/movt pick library pointers 6–8 = curves 0,1,2 (HDR) or the stock 6,7,8
(Retro's set) and `stm` them to RAM 0x5503761C on every Make. HDR keeps selector 3. Emulated: `verify_films.py` ALL OK,
`work/films_v4/seqcheck.py` (Retro→HDR→Retro→Standard→HDR→Retro in one session, still + LV) curve err ≤1 /16384.
Fit `work/films_v4/fits/pro400h_own_b4n3.json` (`--boost 4 --neutral 3`), others = v3.

| Pro 400H | v3 (Gold curves) | v4 (own curves) |
|---|---|---|
| chart dE | 3.23 | 2.52 |
| general dE | 3.39 | 2.84 |
| warm dE / hue err | 3.22 / +2.5° | 3.04 / +2.5° |
| test2 scene neutral / warm / other | 2.52 / 4.18 / 2.75 | 1.11 / 3.35 / 1.98 |

Output `work/films_v4/fwdc239b.bin` (SHA-256 bfe42f3b…8e79eed). Not yet camera-tested.

Next lever (needs one camera test): a neutral-preserving 3×3 after the curves (gamma domain) would cut warm dE a lot at
equal general dE (`work/films_v4/postgamma_ceiling.py`: warm Portra 3.38→2.26, Gold 3.12→2.51, Ektar 4.59→2.68,
400H 3.04→2.34). Candidate hardware: CCA1 (info+0x1220, after GAM in the R2Y order; 2-bit ctl from ColorMatrix
out+0x30, stock 0 = off; 12-bit coefficients from out+0x32…) or the YCbCrMatrix (hue) block.

## 21. RAW noise reduction (PPU Bayer NR) — films v5 turns it off (built 2026-10-08, offline)
No menu item controls it. The RAW is filtered in the **PPU** (sensor front end: SLVS-EC RX, OBC, DPC/SDPC/DDPC, PDSP,
NR; registers NR_ENABLE 0xA2, NR_NOISE_Y_0..19 0xA4.., NR_NSCALE_*, NR_ALPHA) before the main SoC and the DNG writer.
- Debug-flag object (singleton getter 0x53654150, ctor 0x536533b0 = name table obj+0x204+4i, value obj+0x105+i,
  get 0x53654220, set 0x5365422c only if obj+6+i). Relevant: 0x1F DISABLE_ALL_NR (only dark-frame/long-exposure
  decisions 0x53512bec/0x53512e28), 0x52 DISABLE_ELF_NR (never read), 0x77 DISABLE_PPU_NR, 0x7C DISABLE_PPU_NR_PARAM,
  0xA5 DISABLE_PPU_ALL. All stock 0.
- Still FE setup 0x53434040 → 0x5343322c: out+0x64 = NR unit on = !cfgsrc[1] (0 if flag 0x77), out+0x69 = NR param
  on = !cfgsrc[4] (0 if 0x7C); cfgsrc = obj+0x60, a runtime message payload (handler 0x5342da10). Siblings: out+0x66
  SDPC, +0x67 DDPC, +0x68 PDSP. The PPU config cfg = out+0x50.
- PPU start 0x53642e78: enable mask bit0 always, bit1 cfg+0x16, bit2 +0x17, **bit3 = NR (cfg+0x14)**, bit4 +0x18 (0x20
  only if DISABLE_PPU_ALL) → driver 0x5380cc04. Alternate path 0x53642a84 sets bit 3 from cfg+2.
- NR parameters 0x53642b24 → NRUnit 0x536edbbc: p[0] = ISO index cfg+0x2c (= 8·(Sv−1); ISO100 = 32, 200 = 40,
  800 = 56, 3200 = 72, 6400 = 80, 25600 = 96), p[1] = mode 0 if cfg+0x19 else 3. Tables (RAM 0x550375AC..FC → ROM
  0x53EF12C4..0x53EFA33C, 12-byte A + 20-byte B entries × 144 ISO steps, 2 variants): mode 0 B enable from index 36
  (ISO ~140), strength byte 8 @ISO200, 0x18 @400, 0x20 from 800, level 0→3 at ISO ~1100/3200/12800; mode 3 never
  enabled. Live view (0x5343f2ec) uses modes 1/2.
- Patch (`raw_nr.py`, `make_films.py --raw-nr-off`): 0x5343326C/0x53433284 `eoreq` → `mov r6/r7,#0` (as if flags
  0x77/0x7C were set: unit off, params mode 3) and 0x53642AC4 `orrne r4,r3,#0x18` → `#0x10`. Emulated 0x5343322c:
  stock out(0x64,0x69) = (1,1) for cfgsrc 0 → v5 (0,0). Live view and JPEG NR (R2Y YNR / CNR) untouched.
- Measured (`raw_noise.py`, lag-1 correlation of flat-area noise above white noise): photo-test2 ISO 200 +0.016
  (≈ a 3×3 blur blended in at ~7%, or leftover texture); no high-ISO RAWs yet.
- Output `work/films_v5/fwdc239b.bin` (v4 + the 3 words; SHA-256 72ff8532…65d865), `verify_films.py` ALL OK.
  Not camera-tested; test = dark frames + defocused grey at ISO 200/1600/6400/25600 before/after
  (`work/films_v5/HOW_TO_SHOOT.txt`).

### 21a. Camera test 1 (photo-nr1, 2026-10-08): v5 removes most of the RAW NR
One ISO 25600 shot each of the same floor scene at equal exposure (A stock-NR 1/30 f/3.2, B v5 1/10 f/5.6; black 4032).
Green-plane noise SD in matched-brightness flat blocks: 147→259 (mean 0–60), 167→281 (60–150), 219→333 (150–400),
i.e. +60–75 % noise = the stock RAW was strongly denoised at ISO 25600 and v5 turns it off. Lag-1 excess 0.10→0.075
(not 0): could be texture of the wood floor (horizontal lag 0.107 vs vertical 0.058 in B) or another stage; needs flat
targets (dark frame / defocused grey) to tell. Lower ISOs not tested yet.

### 21b. Films v6: RAW NR only at ISO ≥ 6400 (built 2026-10-08, offline)
`make_films.py --raw-nr-from-6400` (`raw_nr.patch_raw_nr_min_iso`): clears the enable byte (B[0]) of the mode-0 B
entries for ISO index 36..79 in both variants (ROM 0x53EF6868 / 0x53EF9720, 88 bytes), so ISO 140..5000 get the same
"NR off" parameters stock already uses at ISO ≤ 125; ISO ≥ 6400 entries untouched. No code change. Emulated NRUnit
(v4 → v6 B flags): ISO 200 1→0, 800 1→0, 1600 257→256, 3200 257→256, 5000 513→512, 6400/12800/25600 unchanged
(513/513/769). Level bits without the enable bit also occur in stock (mode 2). Mask bit 3 (NR unit) stays on, as at
stock ISO 100. `verify_films.py` ALL OK. Output `work/films_v6/fwdc239b.bin` (SHA-256 30711e24…c8ea25).
Not camera-tested.
Camera test (photo-nr2, ISO 5000, v4 1/80 vs v6 1/100 f/3.2, black 2048): RAW noise SD in matched flat blocks
G 43→60 / 55→80 / 115→162, R 21→60 / 33→82 / 76→143, B 20→57 / 30→87 / 56→124; lag-1 excess R/B +0.13–0.17 →
+0.03–0.05, G +0.06–0.09 → +0.04. So stock smooths R/B (chroma) about 3× harder than G, and v6 removes it at ISO 5000.
JPEG: finer grain + more wood texture in v6 (`work/films_v6/compare_iso5000_crop.jpg`). ISO ≥ 6400 not shot (table unchanged).

### 21c. Films v7: RAW NR only above ISO 8000 (built 2026-10-08, offline)
`make_films.py --raw-nr-above 8000` (`raw_nr.above_index`: midway to the next 1/3 stop, so 8000 = idx 82.7 off,
10000 = 85.3 on → first kept index 84). Clears B[0] for index 36..83 (96 bytes). Emulated NRUnit B flags v4 → v7:
ISO 200 1→0, 5000/6400/8000 513→512, 10000/12800 513 = 513, 25600 769 = 769. `verify_films.py` ALL OK; v6 still
rebuilds bit-identical. Output `work/films_v7/fwdc239b.bin` (SHA-256 a7d60c88…7889b7). Not camera-tested
(same mechanism as v6, confirmed at ISO 5000).

## 22. Factory / engineering menu entry (static, 2026-10-08, not yet tried on camera)

Same mechanism as the camera-verified GR IV and GR IIIx 1.60 (ricoh-gr4-firmware-analysis-and-feature-expansion project):
- Entry file name: 0x536bdc44 / 0x536be854 sprintf `C:\%08ld.%03ld` (0x53d615d8) with 0x5381fe9c = 0x1320E (78350) and
  0x5381fe4c = 0x24C (588) -> **`C:\00078350.588`** (GR IIIx 1.60: 00078490.609, GR IV: 00078560.636).
- Key file: name XOR 0x29 at 0x538f2d84 -> `C:\DEVELOP.MOD`; must be 10 bytes (0x536bf744) equal to key 1
  `07 01 2c 1f 10 03 1e 16 05 2d` (0x53d628a0, mode 1) or key 2 `07 1a 02 0a 19 18 1b 1c 05 11` (0x53d628ac, mode 2).
- Entry file parser 0x536be854: CR-terminated lines, `!`/`;` comments, commands in `[...]`, matched by 0x536bdd80 against the
  0x20-byte table at 0x538f2d94..: DEBUG_MODE EN/DIS, WRITE_CF_VNDR EN/DIS, SCRIPT_EN_MODE EN/DIS, SW_DEBUG_MENU EN/DIS,
  USR_DAT_CLEAR, OPEN_DEBUG_MENU, OPEN_FACTORY_DEBUG_MENU, SWITCH_TEST, RELEASE_AGING, DSP_ROM_STORE, ADJ_DAT_READ/WRITE,
  USR_DAT_READ/WRITE, CAM_LOG_DAT_READ, CAM_LOG_DISP, USR_CLEAR_CAM_DISP, RELEASE_COUNT 0/10/25/50/100, INFORMATION, DEBUG_LOG_RE..
- Menu pages (0x53b21b00..): FW Setting1/2, Setting & Display, Test Display, WLAN / BLE, Camera -> SD, SD -> Camera,
  Screen Shot, Factory Menu, Service Menu. Items include Camera Mode, Script, Key Emulate, Serial Input, Store Debug Log,
  Read/Write Adjust Data, Clear User Data, Set Release Count, Store DSP ROM, Display Camera Info, versions.
- Ready-made files: `work/factory_entry/` (00078350.588 = `[OPEN_FACTORY_DEBUG_MENU]\r\n`, DEVELOP.MOD = key 1).
  Use: copy both to the SD root, hold MENU while switching on (GR IV / IIIx procedure).

### 22a. Camera result (factory-mode/, 2026-10-08): entry works on GR III 2.10
- MENU + power with the §22 files opened the factory menu. User set Camera Mode = Debug, ran Read Adjust Data / camera log,
  shot one photo. Card got KB588.ADJ (this body's calibration backup, ~5 MB, includes the serial number - never publish),
  KB588.CAM (usage counters: release/shutter/power-on/aperture/ND counts, lens error log, firmware versions),
  KB588.DOM (APData00-04 user settings), log0.txt (mostly "log buffer overflowed"). File contents stay off the repo.
- Debug mode adds nothing to the JPEG/DNG (same EXIF/MakerNote tag set; APP7 "RICOH" = 720x480 preview).
- Every boot logs "NOT ADJUSTED ... DEFECT PIXEL DATA" and "wlan and ble control is disabled by adjust data" although the ADJ
  file has its defect-pixel entries (HwPxDfct/SwPxDf*/ZAfDPx*) flagged valid (a55a5aa5). Meaning unverified.

### 22b. Script setting (static)
- Script = Enable: start-up runs `C:\script\startup.ttl` ("start script file is found!!"), power-off runs
  `C:\script\shutdown.ttl`; table 0x540b4c38 also has `C:\script\dbgparam.ttl`. Runner 0x536bbe98 needs obj+0xb0 (enable).
- Interpreter = Tera Term Language subset (keyword ids 0x538c3444, executor switch 0x538c1560): file/folder ops, strings,
  if/while/for/goto/call/include, mpause, random, messagebox, sendln, execcmnd. No wait/connect.
- `sendln` (id 0x4e, 0x538c06ac) calls callback [0x5537e9f0] = 0x536bae2c (set from RAM 0x55018bb4 by 0x538bc6ac), the
  engineering shell line parser ("Shell can't be used in Interrupt."). So scripts can run the 585 SHELLCMD commands
  (names/handlers: SHELLCMD section, list in scratchpad shellcmd.txt): camctl_* (shutter/aperture/ISO/bulb timer/capture/
  interval/multiexp), SW_* button emulation (SwS/SwR half/full press, mode dial, menu...), SYS_md (memory dump to file),
  SYS_reg (get/set register), sys_fwdump, SYS_copylog, med_* file ops, focus_*, CAP_REG_* register dumps, dd_* (adjust
  data save/load - dangerous), lcmd (Linux command). Exact argument syntax unverified on camera.
- Probe: `work/script_probe1/script/startup.ttl` (read-only: marker file, SYS_buildinfo, three SYS_md dumps, SYS_copylog).

### 22c. SpecialFeatureFlag 1-16 (adjust data group 0x23, ids 0x82-0x91, SpFFlg01-16) are unused in fw 2.10
- Objects: classes SpecialFeatureFlag1..16 (vtables 0x53d180b8 + 0x58*k), ctors 0x5353a890 + 0x44*k, statics
  0x55345cd8 / 0x55346ed8.. created by AdjustManager init 0x5352909c into its table at this+4+4*id (emulated: +0x20c..+0x248).
  Each holds a 16-byte record: [0] = a55a5aa5 valid / ffffffff unset, [1] = 32-bit value. User's camera: all unset.
- Consumers read adjust items as `bl 0x53525d5c; ldr rT,[r0,#4]; ldr rX,[rT,#4*(id+1)]`. A scan of all 2107 callers finds
  readers for ids 2,3,4,5,6,17-20,31,38-44,60,80,100-111,146,147,179,180,232 but none for 0x82-0x91; no other code builds
  those ids (only the ctors), and the 9 callers of the generic getter 0x53527514 use ids 2 and 0x14. So the flags are only
  touched by generic load/save (factory Read/Write Adjust Data). Reserved for other models/editions; setting them does nothing.
- Edition (shell `collab off/street/urban/ing/diary`, menu "Collab") and lens filter type (ND/HDF, menu "Set Lens Filter
  Type") are separate settings, not these flags.

### 22d. Probe 1 v2 (built 2026-10-08, not yet run) and what it needs
- CAP_REG_B2Y / CAP_REG_IIP / CAP_Lut / CAP_REG_DMA are stubbed in this build (`mov r0,#0; bx lr`, 25 such commands), so
  R2Y registers must be read from RAM with SYS_md. SYS_md 0x53041e50: `<addr> -s <size> -f <file>` writes raw memory to a
  file via 0x536bb174 (log "Dump memory to %s : OK/NG").
- MMU table 0x53004000 (TTBR0): flat 1:1 map; 0x55000000-0x80000000 normal memory. RW data 0x55000000 (+0x3a080 from ROM
  0x5407b540), bss 0x5503a100-0x55804374, heap after that (code references cluster up to 0x55900000).
- Probe (`work/script_probe1/`): stage 0 = marker, SYS_buildinfo, 3 small dumps, SYS_mplt/SYS_mpft, RAM 0x55000000+8 MB;
  90 s pause (user shoots one photo if the camera is usable); stage 1 = 4 x 16 MB heap dumps 0x55810000-0x59810000,
  SYS_copylog. Progress files P1_*.TXT show where it stopped. Analysis plan: find the ImageTuningStill object (vtable
  0x53DBD8A0) and the info block (R2Y image at info+0x120, CCA1 at info+0x1220) by pointer chase / emulated signatures.

### 22e. Probe 1 result (script-probe1/, v7 firmware, 2026-10-08): scripts + engineering shell work
- Stage 0 completed: P1_NAME.BIN = `C:\%08ld.%03ld` + following ROM strings (exact), so `sendln 'SYS_md ...'` runs the
  shell command and writes raw memory to the card. Camera reached the shooting screen normally (script runs async).
- P1_BTAB.BIN (live NRUnit mode-0 B table, variant 0) has enable 0 for index 0-83 and 1 from 84 = v7 exactly
  (P1_BPTR = 0x53EF9720 / 0x53EF6868 as expected). **v7 RAW NR cutoff confirmed in the running camera.**
- P1_RAM0.BIN (0x55000000 +8 MB): RW data matches the ROM image except 337 words. No ImageTuning vtable in it (heap object,
  created by 0x536f0304 -> owner+4). Heap pointers in it cluster at 0x570-0x573xxxxx and 0x591-0x59Cxxxxx.
- Stage 1 never started (no P1_S1GO.TXT): either the camera was switched off within 90 s of the stage-0 dumps, or the
  script stops later (mpause / mode change). Probe 2 adds 10 s heartbeats and dumps 0x55000000-0x56F00000 (via 2 files),
  0x56F00000-0x58000000, 0x58800000-0x59E00000 at t = 60 s.

### 22f. Probe 2 result (script-probe2/, v7, R0011827 Vivid ISO 5000, 2026-10-08): live R2Y block read back
- Script stays alive the whole time (15 heartbeats over 150 s) while the camera is used normally. P2LOG not created
  (SYS_copylog path form wrong or not supported); everything else OK.
- ImageTuningStill object at 0x5966b440 (LV object 0x5966b680). Still info blocks found by the emulated Vivid CCA0
  matrix: 0x599aa6a0 (stage byte 1, SI 0x70d48800) and 4 identical copies (0x5972e3e0, 0x597476d0, 0x59929ba0,
  0x599e30d0). **info+0x100..0x11DF (CCA0 matrix, Y-blend, MultiAxial) equal the emulation byte for byte** -> the film
  look in the camera is exactly what verify_films checks. Differences only where run_tuning stubs or ignores inputs
  (+0x11e0 block, gamma/tone tables from +0x1688 etc.: DR auto, shadow correction, ISO 5000).
- CCA1: info+0x1220 ctl = 0, coefficients info+0x1240.. = identity 0x200 (rows at +0x1240/+0x1246/+0x124c), clip
  0xfff at +0x1260. Coefficients come only from ColorMatrix init 0x536DED70 (`strh` of 0x200 to out+0x32/0x3a/0x42,
  0 elsewhere); Make never changes them; writer 0x536DF13C copies out+0x30 (2-bit ctl) and out+0x32..0x42 (12-bit) to
  info+0x1220/0x1240 every shot. By analogy with CC0CTL (0 = x0.5), ctl 0 with 0x200 = unity, i.e. CCA1 is probably
  active as an identity.
- `make_cca1_probe.py` -> `work/cca1_probe/fwdc239b.bin` (SHA-256 7050586f…fc290d) = v7 + 4 strh changes in the init
  (rows (0,0,1)(0,1,0)(1,0,0)). Emulated: only info+0x1240/44/4c/50 change for tones 11/12/19/20/21; RTOS differs from
  v7 in 4 bytes. Plus `work/cca1_probe/script` (probe 3 = probe 2 with P3_ names) for read-back. Not yet flashed.

### 22g. CCA1 is live (photo-cca1, R0011831, 2026-10-08) -> films v8 warm-colour fix (built, not yet camera-tested)
- cca1_probe (rows (0,0,1)(0,1,0)(1,0,0)): camera JPEG shows red and blue exchanged (yellow -> cyan, orange -> blue,
  navy -> brown, purple -> pink), also in live view. Channel correlation JPEG vs DNG render: JPEG R ~ DNG B (0.965),
  JPEG B ~ DNG R (0.975). So CCA1 is an active RGB 3x3 after GAM (the film curves), ctl 0 with 0x200 = 1.0; coefficients
  are 12-bit two's complement (the writer masks with bfi #0xc).
- `cca1_fit.py` (= postgamma_ceiling objective, neutral-preserving rows rounded to sum 512) -> work/films_v8/cca1_mats.json:

| Film | CCA1 (x/512) | warm dE before -> after | general dE |
|---|---|---|---|
| Ektar (Vivid) | [519 21 -28; 29 429 54; -7 20 499] | 4.59 -> 2.68 | 3.53 -> 3.54 |
| Gold (Retro) | [523 2 -13; 24 457 31; -4 19 497] | 3.12 -> 2.51 | 3.24 -> 3.30 |
| Pro 400H (HDR) | [506 30 -24; 14 480 18; -6 32 486] | 3.04 -> 2.33 | 2.84 -> 2.71 |
| Portra (Cross) | [509 29 -26; 26 453 33; 4 8 500] | 3.38 -> 2.27 | 3.30 -> 3.42 |

- `cca1.py` + `make_films.py --cca1 mats.json`: ColorMatrix Make wrapper `bl calc` (0x536DF3E8) -> stub 0x536EF61C that
  looks up the look record [ctx+8] (0x550196D8 / 0x55019108 / 0x55019060 / 0x5501939C) in a table and copies the film's
  9 coefficients (identity for any other record) to obj+0x32, then `b calc`. Stub + table (188 B) sit in the Cross
  "random" preset branch; 0x536EF618 becomes `b 0x536EF6DC` (fixed-preset case) so that branch is dead.
- `work/films_v8/fwdc239b.bin` (SHA-256 150fe1098746b644149b47818e43a7db776e22ae2f44a7096f0d5acff44e7727) = v7 flags +
  --cca1. `verify_cca1.py v7 v8 mats`: still and LV over a 13-tone sequence, R2Y identical to v7 except info+0x1240..51 =
  film matrix / identity, ctl 0 -> ALL OK. verify_films ALL OK.

### 22h. Films v8 on camera (photo-v8, R0011832-43, 2026-10-08): CCA1 fix works as modelled
`work/films_v8/check_v8.py` (chart.py finds the 4 corner markers, so camera movement is tolerated; Standard model fit on
R0011833: dE 0.70; WB was Multi Auto). Camera JPEG vs model: v8 model (curves + CCA1) fits 2x better than v7's.

| Film | camera vs v8 / v7 model | camera vs target all / warm | warm hue err | v8 model warm (v7 model) |
|---|---|---|---|---|
| Ektar (Vivid) | 1.12 / 2.43 | 4.07 / 3.59 | -0.3° | 2.85 (4.72) |
| Gold (Retro) | 0.84 / 1.60 | 3.42 / 2.75 | -1.5° | 2.44 (3.28) |
| Pro 400H (HDR) | 0.85 / 1.46 | 2.87 / 2.51 | +0.9° | 2.05 (2.90) |
| Portra (Cross) | 0.89 / 1.64 | 3.61 / 2.59 | -0.4° | 2.21 (3.21) |

Warm colours (target C>20, hue 30-100°) on camera: Ektar 3.59 (v3 chart test: 4.40), Gold 2.75 (3.11), Portra 2.59 (2.91).
Overall model error +0.05..0.2 (fit objective trades a little general accuracy).
Hand shots (`hand_compare.py`, R0011842 Ektar / R0011843 Portra, forearm patch, Lab): v8 moves skin only slightly
(hue +0.7..1.1°, chroma ±0.3 vs v7 simulated by undoing CCA1). The spektrafilm target rendered from the DNG is
~5-6° yellower and 3-6 chroma richer on skin (Ektar 53.6°/22.3 vs 48.9°/16.6; Portra 54.6°/18.3 vs 49.1°/15.1): skin
(C~15) is below the warm-set chroma cut (C>20), so the CCA1 fit barely weighted it. Next lever: skin-weighted refit.

### 22i. Films v9: joint refit of look matrix + curves + CCA1 (built 2026-10-08, not yet camera-tested)
v8 only added CCA1 on top of fixed v3/v4 fits. `joint_fit.py` alternates CCA1 (LS), curves (fit to target pulled back
through CCA1^-1) and look matrix, 6 rounds, same samples/weights as the original fits, CCA1 rounded to x/512 and curves
refitted against it. Fits: work/films_v9/fits/*_joint.json (with `cca1_q512`), mats work/films_v9/cca1_mats.json.

| Film | general dE v7 -> v9 | ColorChecker | warm | CCA1 (x/512) |
|---|---|---|---|---|
| Ektar | 3.53 -> 2.77 | 3.25 -> 1.79 | 4.59 -> 2.38 | [512 35 -35; 35 406 71; 12 59 441] |
| Gold | 3.24 -> 2.48 | 2.62 -> 1.61 | 3.12 -> 1.91 | [541 -7 -22; 42 406 64; 6 56 450] |
| Pro 400H | 2.84 -> 2.42 | 2.52 -> 1.62 | 3.04 -> 2.09 | [504 55 -47; 33 449 30; 1 76 435] |
| Portra | 3.30 -> 2.58 | 2.86 -> 1.65 | 3.38 -> 1.96 | [513 40 -41; 38 409 65; 14 49 449] |

Prediction on the real photo-v8 chart patches (`work/films_v9/predict_v9.py`, model vs target): Ektar 3.46 -> 2.65,
Gold 3.07 -> 2.19, 400H 2.54 -> 2.05, Portra 3.25 -> 2.31 (v8 -> v9). Forearm: hue Ektar 48.1 -> 51.1° (target 53.7),
Portra 49.6 -> 52.6° (54.5), chroma unchanged (target richer).
`work/films_v9/fwdc239b.bin` SHA-256 0bc9c8eb63f94034d8d611207c32f416944a702692f40fb95563ab819624d28b
(make_films --raw-nr-above 8000 --cca1 work/films_v9/cca1_mats.json + joint fits). verify_films ALL OK, verify_cca1 (vs
the same build without --cca1) ALL OK.

### 22j. photo-v9 (R0011848-55, Daylight WB, 2026-10-08): the camera rendered v8, not v9
`work/films_v9/check_v9.py`: camera vs v9 model dE 1.73-1.83 with a consistent green/light offset (da -1.1..-2.0), worse
than vs the v8 model (Ektar 1.57, Portra 1.47). Regressing (camera - v9 model) on (v8 model - v9 model) per channel gives
slope 0.88-1.10, corr 0.72-0.81 for all four films -> the shots were taken on v8 firmware (flash not applied / wrong file).
Camera vs target on these Daylight-WB shots (v8 rendering): Ektar 3.64, Gold 3.20, 400H 2.90, Portra 3.17.
`work/fw_check/script/startup.ttl` dumps 0x536EF618 +0x120 (stub + CCA1 table) to C:\FW_CCA1.BIN; compare with
work/fw_check/expect_v8.bin / expect_v9.bin to identify the running build.

### 22k. photo-v9 rerun (R0011856-62) + FW_CCA1.BIN: v9 IS running; gap is only on extreme colours
FW_CCA1.BIN (fw_check script, RAM 0x536EF618 +0x120) == expect_v9.bin byte for byte, so §22j's "camera rendered v8" was
wrong. The camera-vs-model gap (dE ~1.8) sits almost entirely in chart rows 0-1 (full-brightness, saturation 1.0/0.6
monitor colours): camera brighter and less red there (dL +3, da -4..-5), i.e. a saturation/gamut compression the model
lacks; no free post- or pre-matrix refit removes it (stays ~1.7). On rows 2-6 (normal colours) camera vs target:
v8 -> v9 Ektar 3.38 -> 2.73, Gold 2.95 -> 2.51, 400H 2.42 -> 2.40, Portra 3.05 -> 2.42 (v9 model predicts 2.52/2.16/2.06/2.13).
Open: model the high-chroma compression (e.g. CCA0 Y-dependent blend / clipping) so fits stop over-pushing saturated colours.

### 22l. CCA1 acts BEFORE the gamma curves -> films v10 (post matrix via the YCbCr matrix, + 5th film)
The §22k "high-chroma compression" is not a missing stage: CCA1 is applied in the linear domain right after CCA0, i.e.
camera = curves(base(C M L)), not clip(curves(base(M L)) C). With that model, camera vs model on the hue chart drops
from 0.93 -> 0.58 (v8) and 1.81 -> 0.61 (v9) mean dE over all four films, the same as the Standard model's own floor
(0.64); every chart row fits (rows 0-1 4.5/3.7 -> ~0.6). Rejected alternatives: CCA1 before the film curves but after
base gamma (1.74), CCA1 in a power-gamma domain (best 1.5), transposed (4.5-9), free post 3x3 (1.7), Y taken from a
separate Y gamma path (2.5). The R/B swap probe (§22g) could not tell linear from post-gamma (a permutation commutes with
per-channel curves of equal shape). So CCA1 is just another linear 3x3 and gives nothing beyond the look matrix.

A real post-gamma 3x3 does exist: the CSP (RGB->YCbCr) matrix, info+0x1180, 9 x 9-bit two's complement, 256 = 1.0,
stock BT.601 (77,150,29 / -43,-85,128 / 128,-107,-21), rotated in Cb/Cr by the Hue parameter (SI+0x77E: hue 0 ->
(-20,-102,122 / 134,-92,-43)). Written by YCbCrMatrix Make 0x536E4760 from obj[0..8] (19-bit two's complement) after its
calc 0x536E4720; [ctx+8] is the look record there too. JPEG decoding inverts BT.601, so H P in the CSP = P applied to
gamma-encoded RGB = exactly what the v8/v9 joint fits assumed.

Free code space, corrected: the Cross "random" case of 0x536EF148 (jump-table entry 0) is 0x536EF618..0x536EF6D8 plus
0x536EF6FC..0x536EF994; 0x536EF6DC..0x536EF6F8 is the LIVE fixed-preset case (entries 1-3). cca1.py's CAVE_END
0x536EF998 was wrong; its v8/v9 blob (188 B) ended at 0x536EF6D8 by luck. A 5th film needs 3 more 256-entry curves
and there is no 1.5 KB of provably free storage, so its curves are stored as 33 knots (step 8, max 34/16384 off the
fit) and expanded at run time into g+0xA08 (packed gamma tables, rewritten from the composite later in the same call).

Films v10 (`film_cave.py`, `make_films10.py`, `armasm.py` = llvm-mc wrapper; `verify_films10.py` ALL OK):
* CSP stub (bl from 0x536E4774): runs the calc, then for a film record replaces H by round(H P/512); hue still works.
* ctx fill tail 0x536DD454 -> cave fill: library slots 6..11 per tone (stock / HDR curves 0-2 / Bleach knot tables),
  selector 12,18 -> 4, 19,20 -> 3, 21 -> 2; the three pointer sets live in the old chain area 0x536DD4B8.
* curve getter call 0x536E87C4 -> stub that expands knot-table pointers into the scratch buffer.
* Bleach Bypass (tone 18, variant slots 22/23 via SI+0x786) -> Kodak Vision3 250D on Kodak 2383 print, own record
  0x55018F94 (copy of the Standard record, Bleach matrix 0x53DC2474 refitted; drops Bleach's toning offset at
  info+0x1674), name "Vision3 250D" (string 0x113), icon "250D" (0x15A). Fit: chart 2.88 -> 1.94 after joint fit,
  Standard vs target 5.8.
* CCA1 stock (identity). Emulated: Standard/mono/Positive/Negative byte-identical to stock (still + LV); every film's
  composite = fitted curves (+-1), CSP = H(hue) P for hue 0/4/8, R2Y vs Standard differs only in CCA0, CSP, gamma.
* Prediction on the photo-v9 chart (all patches, camera v9 -> v10 model): Ektar 3.64 -> 2.62, Gold 3.20 -> 2.20,
  400H 2.91 -> 2.09, Portra 3.14 -> 2.24; Vision3 250D 2.58.
`work/films_v10/fwdc239b.bin` SHA-256 88adfd79d948d6b2e7f023d5e63462309fe9ea7ae8e2a0378838c5c8b25f45e4, RAW NR above
ISO 8000 as v7. `work/films_v10/script` dumps 0x536EF618 +0x380 to C:\FW_V10.BIN (compare work/fw_check/expect_v10.bin).
Not yet camera-tested.

### 22m. Films v10 on camera (photo-v10, R0011890-97, 2026-10-08) -> v11 perceptual refit
v10 renders exactly as modelled: camera vs v10 model (curves, then P via the CSP) dE 0.80 / 0.57 / 0.60 / 0.54 / 0.55
(Ektar/Gold/400H/Portra/Vision3 250D), every chart row 0.4-1.3 (§22l model confirmed). Camera vs target (all 252 patches):
| film | v9 camera | v10 camera |
|---|---|---|
| Ektar 100 | 3.64 | 2.81 |
| Gold 200 | 3.20 | 2.22 |
| Pro 400H | 2.91 | 2.08 |
| Portra 400 | 3.14 | 2.28 |
| Vision3 250D | - | 2.49 |
(`work/films_v10/check_v10.py`.) Residual model-vs-target is mostly chroma: |dC| ~4 vs |dL| ~1, with a systematic
deficit (mean dC -2.1..-2.5): the RGB least squares of cube_fit/joint_fit under-saturates. Headroom test of extra
YCbCr stages on top of the v10 model (RGB-LS fitted): Y-dependent saturation / Cb,Cr offsets / per-hue gain+rotation
(ideal MultiAxial) gain only 0-0.2 on the camera chart -> not worth more RE now.
`lab_fit.py`: same parameters (look matrix, post matrix, curves + 17-knot corrections) refitted on per-sample dE2000.
general / warm / ColorChecker / camera chart (held out), before -> after:
Ektar 2.77/2.38/1.79/2.63 -> 2.32/1.95/1.65/2.30; Gold 2.48/1.91/1.61/2.21 -> 2.10/1.58/1.39/1.87;
400H 2.42/2.09/1.62/2.13 -> 2.07/1.50/1.46/1.95; Portra 2.58/1.96/1.65/2.28 -> 2.14/1.66/1.45/1.98;
Vision3 250D 2.34/2.00/1.94/2.60 -> 2.13/1.66/1.74/2.42. Greys unchanged (dE76 <= 0.67; 250D 1.24 -> 0.55).
Films v11 = make_films10.py with the work/films_v11/fits/*_lab.json fits: SHA-256
90691ea19c205c0740221537c3d4972d826433a5230baf09b88157238c1b48ae, verify_films10 ALL OK, fw check expect_v11.bin
(FW_V11.BIN via work/films_v11/script). Not yet camera-tested.

### 22n. Films v12: Bleach slot -> Fujifilm Classic Neg (built 2026-10-09, not yet camera-tested)
Target: `classic neg_sRGB.cube` from github.com/abpy/FujifilmCameraProfiles (CC BY-NC-SA 4.0; 32^3, input = sRGB-encoded
linear-contrast image, sRGB primaries, clipped at 1). `cube_fit.load_target` gained in_cs 'srgb'; fits now store
spec/in_cs/ev and joint_fit/lab_fit read them via `target_of`. Exposure: -0.88 EV, the offset at which the same set's
Provia cube puts 18% grey where GR Standard does (0.461; Provia then tracks Standard's grey scale within 0.02 from -4 to
+1 EV). Classic Neg at that offset: grey 0.477, darker shadows (-4 EV 0.034 vs 0.041).
Fit (boost 4, neutral 3): cube_fit chart 2.63 (Standard vs target 9.16) -> joint 1.47 -> lab_fit general / warm /
ColorChecker / camera chart 1.51 / 1.16 / 1.14 / 1.33, identical after the 33-knot expansion (max 26/16384).
Post matrix [[487,-3,28],[54,431,27],[-47,130,429]]/512, CSP H.P (hue 4) [[86,133,36],[-62,-39,100],[112,-96,-16]].
Build: `make_films10.py --raw-nr-above 8000 --labels v12` with the four v11 fits + `work/films_v12/fits/classicneg_b4n3_lab.json`
(name "Classic Neg", icon "NC"); the same command without --labels and with the v11 Vision3 fit reproduces v11 byte for
byte. `work/films_v12/fwdc239b.bin` SHA-256 7d601db0c9a235aadaf72a363b6be57ba7155cc944296896cf4500224fb846a1,
verify_films10 ALL OK, fw check expect_v12.bin (FW_V12.BIN via work/films_v12/script).

### 22o. Sixth film in the Soft Monotone slot (tone 14): what to patch, and where the space is (static + emulated)
Mono handling for tone 14 (all in the still and live-view ctx fill, no other tone-14 checks in ImageTuning):
* 0x536dc4d8 `cmpne r2,#1` sets ctx+0x79 (mono) for tones 13/14/16; with it the ColorMatrix calc 0x536DEECC ignores the
  record matrix and builds identical rows from the filter-effect weights ctx+0x7c..0x80. `#1` -> `#0` drops tone 14 only.
* Record 14 (0x55019204, own matrix 0x53DC27F0, single reference) carries the mono flag info+0x1669 and the toning
  tables. Emulated: flag patch + Standard record on slot 14 -> R2Y byte-identical to Standard (still and LV); toning
  (SI+0x785) and filter effect (SI+0x78A) then change nothing; saturation/hue fixed at 4 by the tone-14 param case
  (0x536DB9D8); contrast/key still read.
* 0x535131D8 `cmp r3,#0xe`: tone 14 always sets flag +0x24 in the struct filled by 0x53513504 (other tones only when
  SI+0x793/0x794 != 4 or SI+0x795 != 0) - presumably the extra pass of the soft effect. Not yet traced.
Space: v12 leaves 36 B (area A) + 32 B (area B) + 16 B (sets); a sixth film needs ~250 B. Newly free, all unreferenced
(no b/bl, literal or movw/movt references from outside):
* C = 0x536EF088..0x536EF140 (184 B): Box-Muller gaussian helper + its literal pool; its only callers (7 bl) were in
  the Cross "random" case that film_cave already overwrote.
* D = 0x536EF99C..0x536EF9B8 (28 B): nop after `bl __stack_chk_fail` + the random case's literal pool (doubles
  0, 1000, 2^31/100); 0x536EF998 (bl) and 0x536EF9B8 (a live function, 4 callers) stay.
Layout that fits (sizes from llvm-mc): A <- CSP stub, shortened 204 -> 192 B (ldm, row/column base registers);
B <- CSP table 7 x 24 + expander 88 + Bleach and 500T knots 2 x 198 (range check 396) = 652/668;
C <- fill (+ tone 14: selector 4, pointer set via movw/movt) 116 + getter 60 = 176/184; D <- 500T pointer set 24/28.
More space (2026-10-09, scratchpad deadscan): whole-RTOS scan for function regions with no b/bl/blx, literal, adr,
pc-relative load or movw/movt reference from outside themselves. On the v12 image it flags exactly one new region,
C above; the look data orphaned by the film records are 8-20 B fragments. In stock, 0x530xxxxx looked dead (135 KB)
until the 584 SHELLCMD handlers were counted as references (engineering shell, reachable from scripts); what remains
is ~52 KB: ~47 KB in one -O0 driver-style library at 0x5307..0x530F (no strings), ~3 KB in app/library code (largest
0x53819B34 776 B, 0x53613114 200 B). Static evidence only (a computed address or a caller outside the RTOS image
would be invisible), so not used. Cheaper: knots as u16 first value + u8 deltas x8 (fits so far: max delta 993,
error <= 4/16384) = 102 B per film instead of 198.

## 23. More Image Control entries (new tones) instead of replacing modes (static analysis, 2026-10-09, nothing built)
Goal (user decision): 6-8 new entries; stock Vivid / Retro / HDR Tone / Cross Process / Bleach Bypass come back
unchanged; the films move to the new entries.

**Menu list (Model/ImageControlModel.cpp).** GetImageControlValueCount 0x532C2A9C: 12 still / 10 movie
(`movls r0,#0xc` at 0x532C2ACC). [obj+0x1B] mode: 0 still, 1 movie, 2 RAW development (masked with 0xFD, so RAW
development shares the still tables). Index -> tone GetImageControlFromUserDataValues 0x532C2C80, one table per
Image Control set (GetActiveImageControlSet 0x532BD6D4, sets No0/No1/No2): 0x53B59224 / 0x53B58FCC / 0x53B5919C,
each `[11,12,13,14,15,16,22,17,18,19,20,21]` and packed against other data (relocate them, one movw/movt pair each
in 0x532C2C80 and 0x532C2F08). Tone -> index 0x532C2F08 is a linear search, `cmp r0,#0xc` (not found -> 12).

**Tones 23/24 are taken.** GetStillDispImageControl 0x5326C1D0 (tone -> display code): set No1/No2 -> 0x17/0x18
(shown as Custom 1/2), otherwise a jump table over tones 0..22 (`cmp r3,#0x16` at 0x5326C238; 0-10 -> legacy codes,
11-22 -> same value). So new tones start at **25**. Display code -> string 0x532A9860, -> icon 0x532A998C (jump
tables `cmp r1,#0x18`, codes 0-10 give 0). Tone -> string 0x532922B4 and tone -> icon 0x532935DC (cmp chains up to
0x16; also reached via GetImageControlString 0x532A9BB0 / GetImageControlIcon 0x532A9B34, which return 0x117/0x118
and 0x15B/0x15C for sets No1/No2).

**Names and icons.** The two string getters (0x53396670, 0x533970A4) index 0x55002BAC[lang][id] with `id <= 0x311`;
new names can be served from cave entries behind these two bounds checks. Icon catalog 0x550020FC, getters
0x53209FB8 / 0x53209FEC / 0x5320A7AC with `id <= 0x29E`; icon pixels live in ICONBIN (not growable in the current
builder). I found no provably unused 40x40 icon (all 388 ids also occur as small immediates, so the scan is
inconclusive) -> icon source still open.

**Where the choice is stored.** User settings struct, 0xB26 bytes (memcpy 0x5327B35C; the factory-default builder
0x5323F42C fills it on the stack, u16 fields). Tone byte (raw tone) +0x1C2 / +0x1C4 / +0x1C6 for still sets
No0/No1/No2 (store functions 0x5327B394 / 0x5327B3B4 / 0x5327B3D4), +0x1C0 = active set, +0x44 checked as well
(still/movie). Every adjustment has one field per mode per set (about 380 store functions, e.g. Standard
saturation No0 +0x1C8, Negative +0xA42), each followed by an "is this the active mode" check before pushing the
value to the camera (0x5354C230 = property 0xAF saturation, ...). "Apply all" 0x532750FC (20 KB, bl'd as 0x532750F8)
calls every check, so values are pushed only for the active tone/set. Check layouts: set No0 = 12 words
`ldr r3,[r0,#4]; ldrb r2,[r3,#0x44]; cmp r2,#0; bne R; ldr r3,[r3,#0x1c0]; bic ..ff000000; bic ..ff00;
cmp r3,#tone<<16; beq T; R: mov r0,#0; bx lr; T: b tail`; No1/No2 = 13 words (`ldrb [0x1c0] == 1/2`, then
`ldrb r3,[r3,#0x1c4/0x1c6]; cmp r3,#tone`). 106 No0 checks matched the exact pattern.

**Per-tone code in the UI model.** The setters read the tone via 0x53549EE8 -> SI+0x77C (only those 20 callers).
109 tone jump tables `sub rX,rX,#0xb; cmp rX,#0xb; ldrls pc` over tones 11-22 in 25 functions: Set* and
GetDefaultValue* for Saturation, ColorHue, ImageKey, Contrast, ContrastHighLight, ContrastShadow, Sharpness,
Shading, ClarityControl (6 tables each = 2 modes x 3 sets; Clarity 3), plus single tables in 0x53356D38, 0x53356E54,
0x53356F70, 0x5336BF28, 0x5336C024, 0x5336C120, 0x53816CE8 (not identified yet). Registers r4/r5/r0 only, rd == rn.
A new tone falls to the default case (setter: nothing stored; getter: assert + fallback). The assert 0x536B93D0
prints a banner and backtrace and returns (not fatal). There is a second enum (UserData::ImageControl 0..11,
order Std, Vivid, Mono, Soft, Hard, HiCon, Negative, Positive, Bleach, Retro, HDR, Cross; 12 = take from SI),
used by GetUserDataImageControlParameterValue 0x53286568, ConvertToCommonPropertyImageControl 0x5328905C and the
RAW-development model (0x53288D60) - still to be checked for new tones.

**Menu -> camera.** The UI sends the raw tone byte: CommonProperty SetImageTone 0x53558310 -> 0x53558260 writes
SI+0x77C; its permission check 0x53553AD4 returns 1 for any value >= 0x16, so no cap. The remote/PTP property 0x4F
handler 0x535BF7A8 maps 0x101..0x10B -> tones 12..22 and anything else to Standard (only matters for remote
control).

**Image pipeline.** ctx fill 0x536DC26C: record slot = tone (22 -> 25; 18/20 special) into the 26-entry record
table 0x55018D94 (also 0x55018CF0, 0x55018E4C). Tones 23-25 would get Bleach-variant / HDR-mono / Negative records,
26+ read past the table -> patch 0x536DC280 to map new tones to the unused legacy slots 0-10 (11 complete
records). The other tone tests in Make are equality tests, so a new tone takes the generic (Standard-like) path,
which is what the films build on. The stock still path only ever sets curve selector 2/3/4 (0x536DD4B8 chain from
SI+0x797), never 1, so the Cross "random" case stays dead with stock Cross Process restored, and library curves
0-2 (3 x 512 B ROM) are only reachable from that case or saved sets.

**Space.** The L1 table at 0x53004000 maps 0x53000000-0x54FFFFFF read-only and executable (AP=2, APX=1);
BSS is 0x5503A100..0x55804374 (boot 0x53000368..). Nothing references 0x540B55C0 (end of the RTOS image) ..0x54FFFFFF,
so code appended to RTOS would sit in memory nobody writes, but whether BOOT loads more than the stock section
length is not verified (only the section header carries the length; PARTPARA not decoded) -> don't grow RTOS
before that is proven. Film curves as knots (§22l/§22o).

**Plan (proxy design).** New tones 25.., each mapped to a legacy record; one "proxy" mode (e.g. Positive Film, 17)
for the adjustments: each `sub rX,rX,#0xb` above becomes `bl stub_rX` (stub: tone >= 25 -> proxy; then -11; the
sites are in non-leaf functions, lr liveness still to be checked per site), and the proxy's No0/No1/No2 checks are
rewritten in place to also accept tones >= 25 (fits exactly: 12 / 13 words using ip as scratch). Films then share
the proxy mode's adjustment values. Plus: list tables + counts, display/name/icon cases, slot map, film fill/CSP.
Open, camera test needed: list screen with > 12 rows, power-off persistence of a tone >= 25, the adjustment page for
a new tone, EXIF maker-note image tone.

## 24. Films v13: six films as NEW Image Control entries, stock modes restored (built 2026-10-09, not yet camera-tested)
`make_slots.py` (from the **stock** file), check `verify_slots.py`, reproduce with `work/films_v13/build.sh`.
`work/films_v13/fwdc239b.bin` SHA-256 6d4d6812f1873b951589db32a617b1e49f9e483a4262b5b5f6762716079a4bce, only RTOS
changed, verify ALL OK (51 checks). RAW NR above ISO 8000 as v12.

| Menu position | Tone | Film (fit) | Legacy record slot / matrix | Knots (curves 0-2 ROM) |
|---|---|---|---|---|
| 13 | 25 | Portra 400 (v12 portra lab) | 1 / 0x53DC2B20 | 0x53EFB2E4 |
| 14 | 26 | Ektar 100 | 2 / 0x53DC2A54 | 0x53EFB3AC |
| 15 | 27 | Gold 200 | 3 / 0x53DC29F0 | 0x53EFC128 |
| 16 | 28 | Pro 400H | 4 / 0x53DC2684 | 0x53EFC1F0 |
| 17 | 29 | Vision3 250D (v11 lab) | 5 / 0x53DC2B8C | 0x53EFC728 |
| 18 | 30 | Classic Neg | 7 / 0x53DC241C | 0x53EFC7F0 |

All curves are 33-knot tables now (max 31/16384 off the fit; v12 kept full curves for four films). Stock modes,
Cross presets and Bleach/HDR variants are byte-identical to stock in the emulated R2Y block (still and LV), also
when rendered right after a film (the fill restores library pointers 6-11 every call; Cross 21 goes through the
stock preset chain 0x536DD4B8).

**One more pipeline finding.** The per-tone parameter pass-through 0x536DB7DC (cmp chain over tones 11-22) forces
every adjustment to neutral (4) for any other tone, so a film on a new tone ignored saturation/hue/contrast/... even
in the pipeline (the CSP hue rotation was missing in the first build). Patch: `cmp r2,#0xb` at 0x536DB7FC -> stub
mapping tones >= 25 to PROXY (17, same case as Vivid). Emulated: film = stock Positive Film with the film's matrix
for saturation 1/7, key 0/8, contrast 1/8, HL 0, shadow 8, sharpness 8 (differences only in gamma, CSP and the
composite flag info+0x82AF). Table 0x53DBD1B0 (per-tone offset into ctx+0x4E, read at 0x536DD3F4) gives 0 for
tones > 22, i.e. Standard's value (Positive has 1); left as is since the fits are made against Standard.

**Patches.** Pipeline: 0x536DC280 slot map (bl + 2 nop), 0x536DB7FC param tone, 0x536DD450/54 fill, 0x536E4774 CSP
stub, 0x536E87C4 curve getter (knot expander with 3 ranges), 0x536EF618 random case -> preset case. Menu: count
0x532C2ACC (18), index->tone table 0x53EFC300 (3 movw/movt pairs in 0x532C2C80, 3 in 0x532C2F08, 3 `cmp #0xc`),
name 0x532922B4 / icon 0x532935DC entry branches, display code 0x5326C240, display string 0x532A9874, display icon
0x532A99A0, string getters 0x533966D4/FC and 0x533970EC/0x53397108 (ids up to 0x3FF; 0x380.. -> entries at
0x53EFC2D0, same text in all languages). Adjustments: 102 tone switches in the 18 Set*/GetDefaultValue* functions ->
bl to r4/r5 stubs (the 7 other single switches are debug printers, left alone); 27 PROXY checks rewritten in place
(12/13 words, ip as scratch). lr is never read in the patched functions before being written (checked), so the
bl's are safe. Free space left: 8 + 4 + 44 + 28 B code, 28 B in the curve areas (a 7th/8th film needs the compact knots of §22o or more dead code).

**Not verified (camera):** list with 18 rows, power-off persistence of tones 25-30, which sliders the parameter page
shows for a film, shooting-screen name/icon, EXIF image tone, playback RAW development and Custom 1/2 with a film,
any other per-tone code outside the patched functions. Icons: all films show the Positive Film icon (no free icon
storage found). Going back to older firmware with a film selected leaves tone 25+ in the user settings - select a
stock mode first. Test plan: `work/films_v13/HOW_TO_TEST.txt`.

### 24a. Films v13 on camera, first look (user report, 2026-10-09)
Test plan items 1-4 (`work/films_v13/HOW_TO_TEST.txt`) reported OK: 18-entry list with the six films after Cross
Processing, Portra 400 selectable with name/icon on the shooting screen, film adjustments shared with Positive Film,
Vivid / Retro / HDR Tone / Cross Processing / Bleach Bypass stock again. Power off / on: the film selection is kept
(user confirmed), so tone 25+ survives in the user settings. Not yet done: chart test (item 5), playback RAW
development and Custom 1/2 with a film (item 6).
Shots (photo-v13, R0011936-38, indoor desk, Multi Auto WB, DR expansion Auto, ISO 400-640): EXIF Pentax ImageTone
is 256 (Standard) for every film - the maker-note writer maps unknown tones to Standard. `work/films_v13/check_v13.py`
(run in a venv with rawpy/opencv/colour/scipy) compares each JPG with the Standard model and all six film models
developed from its own DNG (mean dE2000, exposure + shading gain fitted per model):
| shot | Standard | Portra | Ektar | Gold | 400H | 250D | Classic Neg |
|---|---|---|---|---|---|---|---|
| R0011936 | 5.14 | 5.45 | 5.63 | 5.02 | 4.40 | 4.07 | **1.52** |
| R0011937 | 2.06 | 1.63 | 2.33 | **1.59** | 3.45 | 4.54 | 6.38 |
| R0011938 (Saturation High in EXIF) | 3.06 | **2.60** | 3.10 | 2.70 | 4.50 | 5.71 | 7.57 |
R0011936 is unmistakably Classic Neg at the v12 level (v12 camera vs model 1.2-1.5), so a film on a new tone renders
as modelled. R0011937/38 can't be told apart between Portra and Gold from the scene alone (and R0011938 has a
saturation change the model doesn't include); which modes were used still to be confirmed by the user.

### 24b. Films v13b: an own icon per film (built 2026-10-10, not yet camera-tested)
Same build plus icons (`make_slots.patch_film_icons`, `work/films_v13b/`, SHA-256
4ba9797208b413312904f5c345d6516bf42f73034911e8046896db494097db3f, verify ALL OK incl. an ICONBIN check). ICONBIN can't
grow and no 40x40 icon is provably unused, but this firmware serves GR III, GR III HDF, GR IIIx and GR IIIx HDF
(model strings), so model-specific icons are free on a plain GR III: HDF on/off 0x05-0x07 (40x40, redrawn in place),
GR IIIx certification marks 0x1D (720x360; the GR III page is 0x1E with FCC ID 2ACZS-R02010, 0x1D shows R05010),
GR IIIx TELE 0x2D and 71mm crop 0x2E. 0x1D/0x2D/0x2E get 40x40 descriptors (descriptors are in RTOS rodata,
0x53B5xxxx) pointing into 0x1D's pixel area (3 x 6400 of its 1,036,800 B). The icon caves return ids from a table:
Portra 0x05 "P400", Ektar 0x06 "E100", Gold 0x07 "G200", 400H 0x1D, 250D 0x2D, Classic Neg 0x2E, drawn as the
Positive Film strip with the v12 labels (`work/films_v13b/icons.png`). Not for HDF or IIIx cameras.

### 24c. Films v13c: adjustments shared with Standard (built 2026-10-10, not yet camera-tested)
User choice: the films share Standard's sliders instead of Positive Film's. `make_slots.PROXY` 17 -> 11 (nothing else
changed; `work/films_v13c/`, SHA-256 c96cdee737a33ac8877ecb3586b4e107245758aff885228d309af8cd0d332ab9, verify ALL OK,
52 checks, the verifier's reference matrix follows PROXY). Standard has the same nine adjustments as Positive Film
(still jump tables: saturation/hue in Std, Vivid, Positive, Bleach, Retro, HDR, Cross, Negative; key, contrast, HL,
shadow, sharpness, shading in all but HDR; clarity in all but Soft mono and HDR), 27 checks as well, and its case
0x536DBAA4 in the pipeline pass-through does the same as Positive's 0x536DB8FC (raw values from SI+0x77D..0x784,
0x793/0x794). Per-film storage was ruled out: no known spare bytes in the 0xB26-byte user settings (90-320 B needed)
and about 84 B code left.

## 25. Films v14: Cinema (Yellow) / Cinema (Green) / Vision3 500T replace Bleach Bypass / Retro / Cross Process in the still list (built 2026-10-10, not yet camera-tested)
`make_slots14.py` + `verify_slots14.py` (copies of the v13c tools, which still reproduce v13c byte for byte),
`work/films_v14/build.sh`. `work/films_v14/fwdc239b.bin` SHA-256
e7abf7ba2146338bd49557e3f5c1e8ebb55f1719a2bd46824a45f6bf9b99d1bc, verify ALL OK (67 checks). List (sets No0-2, still
and RAW dev): Std, Vivid, Mono, Soft, Hard, HiCon, Negative, Positive, **31 Cinema (Yellow)**, **32 Cinema (Green)**,
HDR, **33 Vision3 500T**, 25-30 films. Movie list untouched; the stock modes stay in the firmware (records, pipeline).
`key@T=fit.json` on the command line = film replaces stock tone T in the list.

**GR IV Cinema (fwdc248b, tones 18/19).** Differs from Standard in look matrix, MultiAxial set and RGB curves. Curve
composite 0x5391E340 (struct per tone {ptr, u8 en, u8 mix, R, G, B} via table 0x55053138): R' = (r0 G + r1 R)/3,
B' = (r0 G + r1 B)/3, G unchanged, r1 = min(ColorTone + 1, 3), r0 = 3 - r1; ColorTone = ctx+0x60 = SI+0x7A6 (0..2,
shown 1..3), both cinema modes mix (emulated). Default ColorTone = 1 for both, every set (defaults struct built by
0x535278D8 at 0x5508A820, +0x1AC/+0x1AD). Base gamma identical to GR III; composite = curve(base) exactly.
Port: matrix = (L4cin L4std^-1) STD_LOOK (same shift from Standard as on the GR IV), curves = mixed curves at
ColorTone 1, no post matrix. MultiAxial (60 zone matrices, strong) not ported (no working MultiAxial on GR III, §18a),
so the port is matrix + curves only. Tools in `work/films_v14/gr4/`.
**Vision3 500T**: spektrafilm 0.3.4 `kodak_vision3_500t` on `kodak_2383` (`spektrafilm-lut build ... --input vlog
--output srgb --resolution 33`, bundle in `work/films_v14/lut_vision3500t_2383/`, CC BY-SA 4.0), fit as 250D
(cube_fit --boost 4 --neutral 3, joint_fit, lab_fit): general / warm / ColorChecker / camera chart 2.27 / 1.72 / 1.54 /
2.27 (Standard vs target 6.74).

**Changes vs v13c.**
* Compact knots: u16 first knot + 32 u8 steps (x8) per curve, 104 B per film (was 198); max error vs the curves
  25-35/16384 for the films, 53/62 for Cinema Y/G. Expander: entry i = knot(i>>3) + step(i>>3)*(i&7). One knot pointer
  per film (curves at +0/+34/+68).
* Records: slots 9, 8, 6 for the three; slot 6's look matrix is shared in stock, so its film matrix lives in the
  curve area. **Slots 6/8 (and 10, 13-16, 24) have the mono YCbCr set 0x53DC5584 in table 0x55018E4C** (hue ignored);
  film slots now get Standard's 0x53DC555C.
* Proxy by table: stub `cmp rX,#25; sublo rX,#11; bxlo lr; ldrb rX,[tab-25+rX]` (ip is never used in the 18
  functions). Standard's 27 checks accept tones 25-30 only (`sub ip,r3,#25; cmp ip,#6; cmphs r3,#11; bls T`); Bleach,
  Retro and Cross each have 30 checks (+ toning / preset), rewritten to accept 31 / 32 / 33.
* Icons: ids 0x2A0-0x2A2 behind the catalog: the id getters' out-of-range path (0x53209FC4/0x53209FF8) and the draw
  function's catalog load (0x5320A80C, bound 0x5320A7CC) serve them from an 8-byte descriptor table; pixels carved
  from 0x1D (6 x 6400 B used). Other 0x29E constants in the RTOS are unrelated (checked).
* Code may also go into the curve area (RX); free after v14: 16+28+28 B code areas, 4+16 B curve area.
* armasm: bls/bhi abs() added.
Not verified on camera: everything above. Replaced stock tones in saved settings (18/19/21 in a still set or Custom)
are no longer in the list (tone->index returns the count) - switch away before flashing.

## 26. Films v15: the three replacements in the movie list too; Cross curves freed (built 2026-10-10, not yet camera-tested)
User choice: replace Bleach Bypass / Retro / Cross Process in the movie list as well, so their storage can be reused
instead of compacting the knots. `make_slots15.py` + `verify_slots15.py`, `work/films_v15/build.sh`;
`work/films_v15/fwdc239b.bin` SHA-256 50d75f3597d1e826ff660ee86a68957c141768ebaa03d72f73ac14b759b3b8dc, verify ALL OK
(73 checks). Only Cross Process frees real space: Bleach/Retro own just a look matrix + toning in their records.
* Movie list: tables 0x53B59234 / 0x53B591C8 / 0x53B5936C (sets No0-2, 10 entries [11,12,13,15,16,22,17,18,19,21])
  patched in place -> [..., 31, 32, 33]; tone->index for movie uses the same tables.
* Movie tone storage: active set +0x57C, set No0 tone +0x57E, No1 +0x580, No2 +0x582. Movie "is active mode" checks
  (81 per set pattern): No0 12 words `ldr [0x57c]; bic; bic; cmp #tone<<16`, No1/No2 13 words `ldrb [0x57c]==set;
  ldrb [0x580/0x582]==tone`. Bleach 27, Retro 27, Cross 30; rewritten to accept 31/32/33.
* GetMovieDispImageControl 0x5326C384 (switch on +0x57E, default 0x5326C3F4 -> fail 0x5326C454, return 0x5326C3E0):
  default -> cave (films = own tone), as the still one.
* The 18 Set*/GetDefaultValue* proxy switches cover the movie tables already (verified per mode).
* Cross gone: the ctx fill no longer branches to the preset chain for tone 21 (stale tone 21 = Cross minus curves,
  diffs only in gamma), so library curves 3-11 (ROM 0x53EFB4E4.., 9 x 512 B) are free. Library areas form three
  runs: 0x53EFB0E4-0x53EFB6E4 (11, 0, 4), 0x53EFB710-0x53EFB910 (3), 0x53EFB928-0x53EFC928 (7, 5, 9, 8, 1, 10, 6, 2).
  Knots (v13c 33 x u16, 198 B, max 36/16384 off the fits) go into the first run = one expander range (cmp #0x600);
  Cinema Y/G store their exact 256-entry curves (6 x 512 B) in the third (pointers outside the knot range, passed
  through unexpanded); composite vs GR IV curves 1/16384. ~1.1 KB left.
* Not emulated: a separate movie-recording pipeline (only still and live view stages), movie-specific permission
  code using the UserData::ImageControl enum.

## 27. How much do sensors differ? (offline estimate, 2026-10-10)

`work/sensor_diff/sens.py` on the RIT camspec database (Jiang et al. 2013, 28 measured cameras, 400-720 nm,
CC BY-NC-SA; no Ricoh, no Fuji, only the old Hasselblad H2 CCD; Pentax K-5 = closest GR proxy). ColorChecker 24
(Ohta spectra), white-preserving 3x3 fitted to minimise dE2000, errors in-sample (so optimistic).
- Camera -> XYZ, best 3x3: typical DSLR 0.65-0.95 mean / 2-3.5 max dE2000; Hasselblad H2 1.5 / 4.5; Pentax K-5 0.8 / 3.0.
- Camera A -> camera B (port a look defined on B's colour): 756 pairs, mean dE median 0.67, 90th pct 1.5;
  worst patch median 2.2. K-5 -> H2 0.97 / 2.3 (cyan, skin, red), K-5 -> Phase One 1.4 / 3.7, K-5 -> NEX-5N 0.5 / 1.6.
- Same camera, D65 matrix reused under tungsten after WB: ~3 mean / 8-10 max (vs ~0.9 / 2.1 with its own A matrix).
=> After a correct 3x3, sensor differences are ~1 dE (worst ~2-4 on cyan/skin/red); the illuminant-dependent matrix
   and the vendor look (non-linear hue/sat tables) are much bigger than the sensor itself.

## 28. GR4-LUTSmith 1.3.0 vs our fits (2026-10-10)

`work/compare/lutsmith13.py` (log `lutsmith13.log`; the 1.2.0 run is `lutsmith.py`/`lutsmith.log`): LUTSmith's own
Fitter/HueFitter, unchanged, on the GR III base gamma with our samples and weights; scored against the same spektrafilm
targets as our v11/v12 lab fits. New in 1.3.0: colour after the curves (= our CSP post matrix) and turns (random starts;
here 3 + a warm start from its 3-curve fit, best kept by the 'general' score, which favours it).
Mean dE2000 general / warm / ColorChecker / camera chart:

| Film | ours (v13+) | LS 3 curves (1.2-level) | LS + after curves | LS + after + hue sectors (GR IV only) |
|---|---|---|---|---|
| Ektar 100 | 2.32 / 1.95 / 1.65 / 2.30 | 4.08 / 4.20 / 3.13 / 3.85 | 3.05 / 2.31 / 1.69 / 2.57 | 2.81 / 2.19 / 1.63 / 2.32 |
| Gold 200 | 2.10 / 1.58 / 1.39 / 1.87 | 3.65 / 3.22 / 2.77 / 3.49 | 2.64 / 2.02 / 1.48 / 2.06 | 2.63 / 2.02 / 1.58 / 2.12 |
| Pro 400H | 2.07 / 1.50 / 1.46 / 1.95 | 3.31 / 2.71 / 2.57 / 3.04 | 2.88 / 1.83 / 1.47 / 2.29 | 2.76 / 1.80 / 1.65 / 2.29 |
| Portra 400 | 2.14 / 1.66 / 1.45 / 1.98 | 3.98 / 3.24 / 3.02 / 3.79 | 2.80 / 2.12 / 1.54 / 2.26 | 2.77 / 2.08 / 1.58 / 2.24 |
| Vision3 250D | 2.13 / 1.66 / 1.73 / 2.42 | 3.61 / 2.62 / 3.35 / 4.21 | 2.61 / 1.62 / 1.90 / 2.75 | 2.52 / 1.58 / 1.84 / 2.65 |
| Classic Neg | 1.51 / 1.16 / 1.14 / 1.33 | 2.68 / 1.61 / 2.33 / 2.46 | 1.64 / 1.00 / 1.07 / 1.77 | 1.32 / 0.94 / 0.86 / 1.10 |

With the same levers the GR III has (matrix, 3 curves, post matrix), ours is better on 21 of 24 numbers and on
'general' for all six (by 0.1-0.8); LUTSmith wins only Vision3 warm and Classic Neg warm/ColorChecker (0.04-0.16).
1.3.0 closed most of the 1.2.0 gap (after curves is the big lever, as for us in v10). With the GR IV hue sectors it
beats us on Classic Neg and roughly ties elsewhere; GR III's MultiAxial never acted on stills (§18a). Its GR IV hue
patch replaces a selector byte table (0x02 x 56) with pointers and the ramp tables with 12 Q10 matrices - a possible
lead for the GR III MultiAxial enable, not checked.

### 28a. GR4-LUTSmith 1.6.0 vs v16 (2026-10-10)
1.4.0-1.6.0 only add slot choice, slot name and icon; Fitter, HueFitter, fit_look, hue_apply_q and post_effective are
byte-identical to 1.3.0, and `work/compare/lutsmith16.py` (log `lutsmith16.log`) reproduces 1.3.0's Classic Neg exactly.
New: Vision3 500T, LS all levers 2.63 / 1.58 / 1.68 / 2.41. With hue sectors now on both sides (v16 joint fits, §33),
general / warm / CC / chart, v16 vs LS 1.6.0 (matrix + curves + after curves + hue sectors): Portra 1.93/1.47/1.38/1.82
vs 2.77/2.08/1.58/2.24; Ektar 2.11/1.77/1.64/2.16 vs 2.81/2.19/1.63/2.32; Gold 1.97/1.48/1.42/1.88 vs
2.63/2.02/1.58/2.12; Pro 400H 1.88/1.30/1.48/1.94 vs 2.76/1.80/1.65/2.29; 250D 1.96/1.45/1.63/2.29 vs
2.52/1.58/1.84/2.65; Classic Neg 1.20/1.01/1.09/1.12 vs 1.32/0.94/0.86/1.10; 500T 1.98/1.43/1.42/1.99 vs
2.63/1.58/1.68/2.41. v16 better on 24/28 numbers, 'general' mean 1.86 vs 2.49; LS keeps Classic Neg warm/CC/chart
and ties Ektar CC.

## 29. GR III vs GR IV MultiAxial sets: same structure, GR IV stock actually uses it (2026-10-10, offline)

GR4-LUTSmith's hue-sector patch (decoded offsets 0x13E68CC/0x13E6954/0x13E69DC and 0x10B1638..; RTOS at decoded
0x17D10) points one slot in GR IV's per-slot MultiAxial set table (3 arrays x 34, 0x55053504 / +0x88 / +0x110, slot 30)
at a new set in a padding area (0x54099928) that copies stock set 0x54049DE8 with its own matrix list (0x54099968).
The GR III has the identical layout: per-slot table 0x55018CF0 (26 slots, all -> 0x53DC2BA0), set = [bounds u16x16,
selectors u8x20, RAM matrix-pointer list x8, 10-bit table object, control u16, YCbCr coeffs]. GR IV's *default* set
0x5404A690 has exactly GR III's values (bounds/selectors 0, thresholds 4095, same control tail). The difference is that
GR IV stock uses active sets: slot 11 -> 0x54049DE8, slots 17/18/19 -> 0x5404A6A8 / 0x5404B800 / 0x5404C6D4, all with:
- bounds (1298,750,0,0, 1448,843,0,0, 1298,750,0,0, 1205,843,0,0): pairs, not 16 monotonic hue boundaries
  (our probes used i*256, i.e. the wrong format);
- selectors 0,1,2,2,2,3,4,5,5,5,6,7,8,8,8,9,10,11,11,11 (12 zones; ours used i or all-equal);
- control 32, 328,328,328, 293,800,1600,2400,3200, 32, **1024,1024,1024,1024**, 0,0,0,0,0, 640,1280
  vs GR III stock 0, 4095 x8, 32, **0,0,21,62**, 0,1,2,7,0, 640,1280. Control[0]=32 and control[10..13]=1024 (Q10 1.0,
  probably zone strengths; GR III 0/0/21/62) were never tried in probe rounds 1-4.
=> Strong lead that §18a's "nothing enables MultiAxial" was a parameter problem, not missing hardware. Next: probe 5 =
GR IV's active set copied verbatim (bounds, selectors, control, marker matrices) into one GR III slot.

## 30. MultiAxial probe, round 5 (built 2026-10-10, not yet shot)
`make_ma_probe5.py` -> `work/ma_probe5/fwdc239b.bin` (SHA-256 0da55084...fd66ff33, on stock 2.10), `verify_ma_probe5.py`
ALL OK (stock modes identical; probe modes differ from Standard only in MultiAxial registers; each ablation differs from
Positive only in its field's registers). GR IV active set (§29, `work/ma_probe5/gr4_std_ma.json`) + marker matrices
(zone z -> grey gain 0.85/0.30/0.75/0.40/0.65/0.50 repeating, all 5 levels):

| Mode | change vs Positive (GR IV set + markers) |
|---|---|
| Positive | - (main test) |
| Vivid | selectors 0 |
| Negative | control[10..20] GR III stock (0,0,21,62,0,1,2,7,0,640,1280) |
| Retro | control[0] 0 |
| HDR Tone | thresholds 4095 |
| Cross | bounds 0 |
Shoot as `work/ma_probe5/HOW_TO_SHOOT.txt` into photo-ma5/.

### 30a. Probe round 5 result (photo-ma6, R0011950-55, 2026-10-10) — **MultiAxial works on GR III stills**
Desk scene (not the hue chart), 1/200 f/2.8 ISO 160 (Cross ISO 125), Multi Auto WB (gains equal within 1 %), no Standard
shot. Per-region JPG mean / high-pass noise SD (wall, paper, screen):
- Negative (control[10..20] back to GR III stock): clean (hf 1.1-1.4), brightest (wall 96) -> MultiAxial off.
- Vivid (selectors 0 = every hue -> zone 0, gain 0.85): clean but darker (wall 86 vs 96) -> MA on, one uniform zone.
- Positive (full GR IV set), Retro (control[0] 0), HDR (thresholds 4095): strong salt-and-pepper (hf 7-9), wall 60-66:
  near-neutral pixels' noisy hue flips them between marker zones (gains 0.30-0.85) -> MA on, zones active.
- Cross (bounds 0): same speckle on the wall/paper but the saturated teal screen is clean (hf 0.8) -> the "bounds" pairs
  gate something chroma-dependent, not the hue partition.
=> The enable is in control[10..20]: GR IV 1024,1024,1024,1024,0,0,0,0,0 vs GR III stock 0,0,21,62,0,1,2,7,0 (most
likely the four 1024s). control[0] and the thresholds are not required. Zone geometry still unmapped (needs the hue chart).

### 30b. Probe round 5 hue chart (photo-ma6 R0011959 Negative = MA off, R0011960 Positive = markers), 2026-10-10
`work/ma_probe5/zones.py <GR4-LUTSmith>` (log `zones.log`): per patch gain Positive/Negative in the linear index
domain, compared with GR4-LUTSmith's GR IV sector model (12 sectors by Cb/Cr angle of the post-look-matrix signal,
edges 359.8, 27.4, 62.2, 92.6, 112.0, 142.8, 179.2, 211.4, 238.6, 267.2, 306.0, 326.5 deg; sector g -> matrices 5g..5g+4).
Measured gains are compressed per chart row (obs = 0.04..0.20 + 0.73..0.92 x marker, larger offset on the darker rows:
monitor flare / black offset, not chroma). After that per-row correction, the 172 coloured patches more than 3 deg from a
sector edge match the predicted marker on 167 (median error 0.025, corr 0.98); the misses are next to edges or between
close markers (0.75/0.85). => GR III MultiAxial = GR IV hue sectors, same geometry and matrix layout; LUTSmith's
HueFitter model applies to the GR III as is. Space: one 60-matrix table (2160 B) per look.

## 31. v16 planning: what hue sectors add to v15 (2026-10-10, offline)
`work/v16_plan/hue15.py <GR4-LUTSmith>` (log `hue15.log`, sectors in `hue_sectors.json`; plan in `work/v16_plan/PLAN.md`).
Sectors-only fit (v15 matrix/curves/post fixed), mean dE2000 general: Portra 2.14->1.96, Ektar 2.32->2.14, Gold
2.10->1.99, 400H 2.06->1.94, Vision3 250D 2.13->1.99, Classic Neg 1.51->1.23, Vision3 500T 2.27->2.03.
GR IV MultiAxial sets (tones 11/17/18/19, `work/ma_probe5/gr4_ma_sets.json`) all use the probe-5 geometry/control; their
5 levels per sector are the level-0 matrix scaled by 1 - l/16. Cinema (Yellow)/(Green) sets vs the v15 port (level 0):
render moves 1.53/1.33 dE2000 mean (camera chart 2.17/1.73, p95 up to 4.8) = what the v15 Cinema port is missing.
Space plan: shared set + compact 72 B/film + register-writing stub after the MultiAxial calc (fits the ~1.1 KB free).

## 32. White balance through the looks (2026-10-10, spectral simulation)
`work/wb_sim/wb_sim.py` (log `wb_sim.log`). ColorChecker 24 (Ohta spectra) x 3 exposures; camspec sensitivities of the
Pentax K-5 (GR III proxy) and Sony NEX-5N; raw -> WB gains -> camera matrix (fitted at D65) -> look (Standard or each v15
film). Reference = the same look on the true scene adapted to D65 (CAT02). Mean / max dE2000, K-5 (NEX-5N within ~0.2):

| Case | Standard | films (range) |
|---|---|---|
| daylight 6500K, ideal AWB | 0.69 / 1.9 | 0.68-0.81 / 2.0-4.2 |
| sun 5000K / shade 7500K | 1.10 / 0.87 | 0.78-1.10 |
| tungsten 2856K, fixed D65 matrix | 3.00 / 12.7 | 2.43-2.89 / 11.5-16.8 |
| fluorescent (FL2 / FL11), white LED 4100K | 2.1-2.5 / 11-14 | 1.5-2.5 / 9-16 |
| same lights, matrix made for that light | 0.49-0.85 / 1.8-3.3 | 0.42-0.92 / 1.4-4.6 |
| daylight, AWB off by ~-1000K / +1000K | 3.88 / 2.97 | 2.8-3.4 / 2.3-2.8 |
| daylight, green gain -3% / +3% | 2.28 / 1.86 | 1.6-2.0 / 1.3-1.7 |
| tungsten, AWB left warm (3200K / 3500K) | 5.7 / 8.4 | 4.7-5.5 / 6.6-8.1 (intended warmth, not an error) |

- The films do not amplify white-balance errors: every case is within ~±0.5 of Standard, usually lower (the film curves
  compress chroma). WB robustness is a camera issue, not a film-fit issue.
- With ideal AWB the error under non-daylight light comes almost entirely from the camera matrix: a matrix fitted for
  that light brings tungsten from 3.0 to 0.85 and fluorescent/LED to ~0.5-0.6. Whether the GR III adapts its
  sensor->RGB matrix to the light is unknown: the R2Y ColorMatrix calc 0x536DEECC only multiplies the look matrix by the
  Saturation matrix (record [+8] list, 9 entries, index ctx+0x57, entry 4 = identity) and an optional fixed matrix
  0x53DC1430 (colour space, ctx+0x52); the sensor matrix is applied before R2Y and was not located. The DNGs carry two
  calibrations (ColorMatrix1/2), which suggests interpolation, unverified.
- Test to settle it: RAW+JPG of a ColorChecker / the hue chart under a tungsten lamp, Standard, AWB; compare with the
  check_v13-style model using the daylight EK. If the JPG matches the model only after a tungsten-specific EK, the camera
  interpolates and the films inherit it; if not, a WB-dependent look-matrix correction would be a v16+ candidate.

## 33. Films v16: hue sectors (MultiAxial) for every film (built 2026-10-10, hue chart camera-tested §33b)
`work/films_v16/build.sh` -> `work/films_v16/fwdc239b.bin` (SHA-256 9d81366c...7faf6d71 incl. §34, §34a, §34c, §34d), `verify_slots16.py` ALL OK (103).
- Fits (`work/films_v16/refit16.py`, log `fits/refit.log`): sectors on v15 -> lab_fit with the sectors in the model ->
  sectors again (LUTSmith HueFitter penalties; off-diagonals in steps of 4/1024). Mean dE2000 general / warm / CC /
  camera chart, v15 -> v16: Portra 2.14/1.66/1.46/1.98 -> 1.93/1.47/1.38/1.82; Ektar 2.32/1.96/1.64/2.29 ->
  2.11/1.77/1.64/2.16; Gold 2.10/1.58/1.39/1.87 -> 1.97/1.48/1.42/1.88; Pro 400H 2.06/1.50/1.45/1.94 ->
  1.88/1.30/1.48/1.94; Vision3 250D 2.13/1.66/1.73/2.42 -> 1.96/1.45/1.63/2.29; Classic Neg 1.51/1.16/1.14/1.33 ->
  1.20/1.01/1.09/1.12; Vision3 500T 2.27/1.72/1.55/2.27 -> 1.98/1.43/1.42/1.99.
- Cinema (Yellow)/(Green): GR IV MultiAxial sets of tones 18/19, level 0 quantised to steps of 4 (max 4/1024 off);
  levels 1-4 = level 0 x (16 - l)/16 in the stub (GR IV's own tables differ from that rule by at most 1/1024).
- Firmware (`make_slots16.py`): stock 10-bit table 0x53DC2BF8 (1440 B zeros; only object 0x55019848 points at it) now
  read from zeros at 0x53D36400 (5404 B zero run in read-only data, no pointers into it); the freed 1440 B hold the
  shared GR IV bounds + selector/control block, 9 x 108 B sector data (12 x 9 int8, matrix = 1024 I + 4 x data) and
  nine 7-word set structs (stock words 0-5 + data pointer | GR IV level flag) in the film slots of 0x55018CF0.
  MultiAxial Make 0x536E4470 -> new Make (176 B, curve area 0x53EFC5E8): stock calc + writer, then for a film set it
  rewrites the 60 matrix registers (regs + 0x100 + 128 sector + 20 level, bfi 12 bits).
- Verified in emulation (still + live view): stock modes 11-22 MultiAxial registers identical to stock (also right
  after a film); each film's registers = GR IV bounds/selectors/control + its matrices at all 5 levels, also after
  another film or Standard; all v15 checks.
- Open: camera test (HOW_TO_TEST.txt), what selects the 5 levels (films use one matrix for all, so only Cinema
  depends on it), movie recording path.

### 33a. v15 vs v16 on earlier real RAW files (offline, 2026-10-10)
`work/films_v16/check_prev.py <GR4-LUTSmith>` (log `check_prev.log`, sheets `preview_*.jpg`: v15 | v16 | target).
DNG -> rawpy linear (camera WB) -> EK (photo-v10 Standard chart) -> exposure from the Standard model fitted to the
camera's own JPG -> each film model (v15 / v16 incl. sectors) vs its target, all usable pixels at 480x320.
Whole photo-v10 chart frame and the three photo-v13 scenes, 7 cube films: mean dE2000 v15 0.94 -> v16 0.84, v16 better
in 28/28 (chart frame: Portra 1.29->1.15, Ektar 1.41->1.29, 500T 1.25->1.09, Classic Neg 0.82->0.74; p95 down 0.1-0.7).
v16 vs v15 change on these scenes 0.14-0.46 mean (p95 0.3-1.7); Cinema Y/G change 0.4-1.25 mean (p95 up to 4.0).
This scores the model against the target; the camera itself is only checked by the earlier validations (v10: camera
vs model 0.55-0.80; §30b: MultiAxial geometry/gains on the probe-5 chart) until photo-v16 exists.

### 33b. v16 on camera: hue chart (photo-v16 R0011993-12005, 2026-10-10)
`work/films_v16/check_v16.py <GR4-LUTSmith>` (log `check_v16.log`; method as check_v13: DNG -> rawpy linear -> EK ->
exposure + radial shading fitted per look, all flat unclipped pixels at 375x250). Shots in list order: Standard, Vivid,
Negative, Positive, Cinema Y, Cinema G, Vision3 500T, Portra, Ektar, Gold, Pro 400H, Vision3 250D, Classic Neg.
- Every film shot is recognised (best of 19 looks = the selected film, runner-up 0.25-2.7 worse).
- Camera vs model, v15 model (no sectors) -> v16 model (sectors): Cinema G 1.12 -> 0.82, 500T 0.66 -> 0.54,
  Portra 0.81 -> 0.78, Ektar 0.74 -> 0.71, Gold 0.80 -> 0.79, Pro 400H 0.72 -> 0.63, 250D 0.75 -> 0.57, Classic Neg
  0.73 -> 0.71: mean 0.79 -> 0.69, v16 closer in 8/8. Standard 0.68. So the camera applies the sector matrices as
  modelled (Cinema G's GR IV set included, level semantics untestable here: a uniform level factor = exposure).
- Cube films vs film target: camera 1.32, v16 model 0.95, v15 model 0.97 (the camera-model gap ~0.7 is the method floor).
- Cinema Y (R0011997) is the exception: 2.74 to either model, +0.65 EV brighter. EXIF Contrast High, Saturation High on
  this shot only: Cinema Y lives in the Bleach Bypass slot and uses that slot's own stored sliders (proxy layout 8), so
  old BB slider values apply. A generic contrast + chroma (x1.46) + gain fit brings it to 1.88. Needs a reshoot with the
  Cinema Y sliders reset.
- Stock Vivid/Negative/Positive: no model here (MultiAxial off for them is verified in emulation only).

## 34. Playback RAW development with films (fixed in v16, 2026-10-10, not yet camera-tested)
User report (v15): RAW development cannot change Image Control to a film. Cause (present since v13, never tested):
RawDevelopmentModel (Model/RawDevelopmentModel.cpp) keeps its own image-control enum per develop slot (+0x83/+0x84/+0x85,
slot index +0x82; 0 = as shot, 1..12 = 11,12,13,14,15,16,22,17,18,19,20,21) with two hard-wired conversions:
ConvertToRawDevelopmentModelImageControl 0x53288D5C (tone -> enum, `sub r1,#0xb; cmp #0xb; ldrls pc`, default
assert -> enum 1 = Standard) and ConvertToCommonPropertyImageControl 0x53289058 (enum -> tone, default assert -> 11).
A film tone therefore became Standard; the RAW-dev slider page (RawDevelopmentImageControlDetailSetController::
GetBaseKindDetailControl 0x5318DEA0) asserted on it too. Parameter cache: 3 x 13 x 17 B at model+0x86; all 62 accessors
look the enum up in 1..12 and use entry 0 (as shot) for anything else, so new enum values are memory-safe.
Fix (make_slots16.patch_rawdev): tone -> enum stub at 0x53288D5C (appended films -> 13..18, replacing films -> the enum of
the replaced mode 9/10/12); enum -> tone: 13..18 -> 25..30 via the default branch, entries of enums 9/10/12 -> 31/32/33;
RAW-dev and shooting slider-page layout (0x5318DEA0 entry, 0x531ACB1C `cmp r4,#0xb` - the earlier `sub` at 0x531ACB00 sits
between a compare and its conditional use, a stub there broke an assertion in emulation) -> the film's proxy layout.
Emulated: stock conversions unchanged, every RAW-dev list entry round-trips tone -> enum -> tone, layouts = proxy, no
assertions. In RAW development a film's sliders use the as-shot parameter cache (entry 0).

### 34a. RAW development list stopped at 12 entries (user report on e27752e1, fixed 2026-10-10, not yet camera-tested)
User (v16 e27752e1): the six appended films do not appear in RAW development (the three replacements do). The RAW-dev
Image Control list (RawDevelopmentImageControlDetailSetController 0x53190108, scroll list 0..count-1) takes its length
from RawDevelopmentModel 0x53283C08 `mov r0,#0xc; bx lr`, hard-wired, not from ImageControlModel's (patched) count;
rows go through 0x53283C80 -> index->tone 0x532C2C80 (mode 2, patched since v13) and selection through 0x532893BC
(tone -> enum, §34). The earlier emulation called 0x532C2C80 for 18 indices directly and so missed the length.
Fix: 0x53283C08 -> `mov r0,#18` (12 + appended films). Neighbour 0x53283CD0 (also 12) is the white-balance list.
Rebuilt `work/films_v16/fwdc239b.bin` SHA-256 9ad5ef4d7149a9a5d9d1c03b6d7d0e9f680ff040f4bf3f754efc3c4edfc8ffb2, ALL OK (100).

### 34b. Camera report on 9ad5ef4d: RAW-dev list still shows only the replacements; film RAWs open as Standard (2026-10-10, solved in §34c / §34d)
User: in RAW development only Cinema Y/G and 500T appear among the films, and RAWs shot in the six appended films "jump
back to Standard". As-shot cause found (static): playback reads the image tone from the file's maker-note ImageTone via
0x535BF7B0 (code - 257 <= 10 -> table 0x53D2D920 -> tones 12..22, anything else -> 11 Standard), and every film shot
(appended and replacing, e.g. R0011997 Cinema Y) is written as ImageTone 256 = Standard, so the as-shot film is lost
before RawDevelopmentModel sees it. Fix needs a film-specific ImageTone code on write (writer not located yet) plus
the reader table; external tools would then show an unknown ImageTone value. List: 0x53283C08 now returns 18 in the
build (checked in the decoded image); why the camera list still ends at 12 is not explained yet - other list paths in
RawDevelopmentImageControlDetailSetController / RawDevelopmentParameterSetController still to check.

### 34c. As-shot film in the file: maker-note ImageTone codes for films (built 2026-10-10, not yet camera-tested)
Writer found: 0x535C780C/0x535C7814 searches a vector of {u8 tone, u8 0, u16 code} (global 0x5534AD6C, built by the
static constructor 0x53599DF0 from 12 pairs at 0x53D2B6F4: tones 11..22 -> 0x100..0x10B) for SI+0x77C and writes
Pentax tag ImageTone via 0x535D02C8; tone not found -> 0x100 (Standard). Reader 0x535BF7A8 (code - 0x101 <= 10 ->
table 0x53D2D920, else 11). Patch (make_slots16.patch_exif_tone): pairs copied + one per film (tone 25+k -> 0x10C+k,
i.e. 268..276), constructor size/count/end to 21 entries; reader `cmp r0,#0xa` -> 19 and table relocated with tones
25..33 appended. Emulated: stock tones write/read unchanged, films write 268..276 and read back their own tone, an
unknown tone still writes 256 -> 11. Old film shots keep 256 in the file and still open as Standard. exiftool shows
the new codes as unknown ImageTone values. (0x536EEFFC/0x536EEE30, a separate tone<->code pair in the tuning-parameter
builder 0x536EF148, is not the maker-note path and was left alone.)
`work/films_v16/fwdc239b.bin` SHA-256 82d2ae46eb7f32a201213366216fc7cd444357d516b9a91de3434c70e1f46e71, ALL OK (101).
The RAW-dev list length (§34b) is still unexplained (solved in §34d).

### 34d. The RAW-dev Image Control list is the parameter screen's own option table (built 2026-10-10, not yet camera-tested)
User photos (82d2ae46): as shot now shows Portra 400 (§34c works); the Image Control list runs ... Nega, Posi, C-Y, C-G,
HDR, 500T, then a '1' (develop setting) entry. That list is RawDevelopmentParameterSetController's Image Control row
(case 8, 0x5318B434), not the detail page of §34a: options = [as shot if the file has one (model+5)] + enum table
0x53B5A988 (1..12) + develop settings 1/2; count 0x53283358 (15/14), option -> slot 0x532834D0 / -> enum 0x532834F0 via
slot table 0x53B5ACB4 ([0]x13 + 1, 2; read at i or i+1), selection 0x53289304 (slot, enum) -> enum at +0x83+slot. Row
capacity (largest option count over all rows; that many list items are allocated) 0x532833BC = 15.
Patch: enum table relocated with 13..12+m appended, slot table with m more zeros, 9 movw/movt, counts 15+m / 14+m,
capacity 15+m. Emulated: 21 / 20 options = as shot, the 12 stock entries (incl. C-Y/C-G/500T), the six films
(enum -> tone 25..30), set1, set2; capacity 21.
`work/films_v16/fwdc239b.bin` SHA-256 9d81366c26281b726ef733d681bbbf2df3febbc438a1967ce254ae997faf6d71, ALL OK (103).

## 35. Aspect ratios 5:4 and XPan (v17, built 2026-10-10, set aside by the user)
make_aspect.py / make_v17.py / verify_aspect.py (ALL OK, 23 emulated checks) turn the hidden GR IV aspect ids 1 (4:3)
and 2 (16:9), still present in GR III fw 2.10, into 5:4 (4992x4000) and XPan (6000x2216): menu, capture sizes,
nails, playback ratio/size checks, crop frames, AF area, DigitalFilter, RAW-dev aspect. Live-view framing not done.
work/films_v17/fwdc239b.bin (c7fdb2e7...) never flashed. The user asked to continue from v16 instead (§36).

## 36. Films v18: Classic Chrome in the Vivid slot; RAW-dev sliders for the appended films (built 2026-10-10, not yet camera-tested)
User (v16): in RAW development the appended films' sliders cannot be adjusted ("does not use the sub-settings from
Standard"). Cause: RawDevelopmentModel's 13-entry parameter cache per develop slot (enum 0 = as shot, 1..12) is
paired with a 13 x 17 "adjustable" flag table 0x53B5A750 whose entry 0 is all zeros; the 81 enum searches of the
model (`mov r3,#1; L: cmp rE,r3; ...; cmp r3,#0xd; bne L; mov rX,#0`, in 0x53283D48..0x53289A38) send an enum outside
1..12 (the appended films' 13..18, §34) to entry 0, so every setter returns before storing (e.g. 0x53286F40
`ldrb [0x53B5A750 + 17*entry]; popeq`). Fix (make_slots18.patch_rawdev_sliders): the 81 not-found results -> 1, i.e.
appended films use Standard's flags and Standard's RAW-dev values (as when shooting). Replacing films keep their
replaced mode's enum. Emulated: accessors for enums 0..12 unchanged, enum 13+ = Standard's entry; the setter with
enum 13 is ignored in stock and stores into entry 1 in v18.
Classic Chrome: `classic chrome_sRGB.cube` (abpy/FujifilmCameraProfiles, CC BY-NC-SA 4.0) fitted as Classic Neg (§22n:
-0.88 EV, boost 4 / neutral 3, joint_fit, lab_fit, hue sectors; work/films_v18/fit_cc.sh). Score general / warm /
ColorChecker / camera chart: cube_fit chart 1.52 (Standard vs target 5.57) -> 1.57 / 1.26 / 1.38 / 1.31 with sectors.
It replaces Vivid (tone 12, key `classicchrome@12`) in the still, RAW-dev and movie lists, using Vivid's slider storage
and RAW-dev enum 2; tone 34, legacy record slot 10 (stock mono look, its record/matrix referenced only by the record
table and the static record list 0x55037634), icon 0x2A3 'CC', maker-note ImageTone 277.
Builder changes, all byte-neutral for v16 (rebuild still 9d81366c): knot tables may spill out of curve region 0 (the
expander gets one more range; Classic Chrome's knots sit in region 1); "is active mode" scans accept every immediate
encoding (`cmp r3,#12<<16` assembles as 3 ror 14, so Vivid's set-No0 and movie checks were missed); MultiAxial data
falls back to the curve area (MA sets 280 B no longer fit the freed table). Free space left: 80 B (+2 x 4 B).
`work/films_v18/fwdc239b.bin` SHA-256 5066f34c5b70a351cf146525b6af31bafa2de589df118f783cc89a73a61750f2,
verify_slots18 ALL OK (114).

## 37. Films v19: RAW NR on/off from the High-ISO NR menu item (built 2026-10-10, never flashed; superseded by v20)
User: "add the option in the setting to set the noise canceling on or off". No free menu item is needed: the stock
High-ISO NR setting is reused. Still settings object = 0x5320b31c() (static 0x55063f30, guard 0x55063ed0), values
block [obj+4]; getters 0x53245294.. read bytes +0x4d0, +0x4d2, ... Labels from the settings-to-text code 0x53366dc0 /
0x53366e28 (name chain 0x53388a8c, names "StillLongTvNR" 0x53b27e08, "StillHighIsoNR" 0x53b27e18):
+0x4d4 Slow Shutter NR (0 Auto, 1 On, 2 Off), **+0x4d6 High-ISO NR (0 Auto, 1 Low, 2 Mid, 3 High, 4 Custom, 5 Off)**.
The PPU NR decisions all ask the debug-flag getter 0x53654220: FE setup 0x53433254 (flag 0x77 -> NR unit out+0x64),
0x53433274 (0x7c -> NR param mode out+0x69), alternate capture path 0x53642AE4 (0x77 -> clears mask bit 3).
Patch (make_slots19.patch_raw_nr_menu): those three `bl` go to a 9-word stub (0x53efc8d8) that returns 1 when
High-ISO NR = Off and tail-calls the real getter otherwise. v19 builds without `--raw-nr-above`, so:
High-ISO NR Off = no RAW NR at any ISO (and no JPEG NR, as stock Off); Auto/Low/Mid/High/Custom = stock RAW NR
(Ricoh's table, NR from ISO ~140). Adding `--raw-nr-above 8000` keeps v18's table for the "on" state instead.
Emulated (verify_slots19, ALL OK 117): FE setup (unit, params) stock (1,1) for every value, v19 (1,1) for values 0..4
and (0,0) for Off, debug flags 0x77/0x7c still honoured; alternate path mask 0x19 -> 0x11 only for Off.
Unknown until camera test: whether the FE setup reads the setting per shot (expected) or only when entering capture
mode. Free space left: 44 B (+2 x 4 B). `work/films_v19/fwdc239b.bin` SHA-256
9fd3426122b91328b96bb22b24bb61b1e854937007b7c84a346654c2a54149ac.

## 38. Films v20: High-ISO NR menu picks the RAW NR threshold and JPEG NR (built 2026-10-10, camera-tested §38a; replaced by v21)
User: "set High to RAW NR on at 3200 and JPG NR off, Mid to RAW NR on at 8000 and JPG NR off". Built on v18 (not v19).
| High-ISO NR | RAW (PPU) NR | JPEG NR |  Auto / Low / Custom: stock / stock;  Mid: from ISO 8000 / off;
High: from ISO 3200 / off;  Off: none / off.
- RAW: the still PPU NR parameters 0x53642b24 (only caller: still PPU start 0x53642e78 @0x53642f44; live view calls
  NRUnit from 0x5343f2ec with its own modes) pass NRUnit mode 0 if cfg+0x19 else 3, ISO index cfg+0x2c. Its
  `ldrb ip,[r1,#0x19]` (0x53642B4C) -> bl stub (0x53efc8d8, 12 words + 8-byte table) that returns 0 when the ISO index
  is below the first index for the menu value: [0,0,81,71,0,255] (from_index = midway down to the previous 1/3 stop:
  3200 -> 71, 8000 -> 81). Same effect as DISABLE_PPU_NR_PARAM per shot; the NR unit stays enabled (as v6/v7).
- JPEG: High-ISO NR setter 0x53252aa0 stores [obj+4]+0x4d6 and, if 0x53252a44 allows, sends camera property 0xdd
  (0x5354cab8 -> 0x5354b564, the only sender of 0xdd; 0x5354e7ec reads it back) to the capture side. The UI value is
  read elsewhere only by menu/text code (0x53197b5c, 0x531b84c8, 0x531c4c6c, 0x53366e3c), a same-offset settings
  copy 0x5326cc44 and a serializer 0x5373e360, so the property is taken to be what the image pipeline uses.
  0x53252ACC `mov r1,r4` -> bl stub (0x53efc910, 5 words): Mid (2) / High (3) are sent as Off (5). Setter callers:
  menu 0x531b6d80, 0x5328b250, settings import by name 0x53307a08.. (all go through the hook).
  Maker note (Pentax tag 0x71 HighISONoiseReduction) is built from the capture side, so it should read Off for Mid/High.
  Inference, not traced to R2Y: confirm on camera that Mid/High JPEGs match Off JPEGs.
- Emulated (verify_slots20 ALL OK 117): NRUnit (ISO, mode) for 6 values x 10 ISOs x cfg+0x19 on/off: stock always
  mode 0 iff cfg+0x19; v20 Mid on at 8000+, High at 3200+, Off never, others = stock, cfg+0x19 = 0 still off.
  Setter: stored value unchanged, sent [0,1,5,5,4,5] (stock [0..5]).
- After flashing, the capture side keeps its last value until the setting is changed: re-select High-ISO NR once.
- Free space now 0 (3 x 4 B). Any further code needs new space.
`work/films_v20/fwdc239b.bin` SHA-256 0b32daef198db05da69d21de460d5b988a8c963601f2ab1195927acdfa30b4a4.

### 38a. Camera test 1 (photo-v20, 2026-10-10): v20 works at ISO 8000
Two RAW+JPG at ISO 8000, 1/80 f/8, same scene, one High-ISO NR = High, one = Off (user did not say which; inferred
from the data: R0012065 = High, R0012064 = Off). raw_noise.py var/mean (Off -> High): R 63.9 -> 23.4, G 59.8 -> 43.2,
B 60.0 -> 23.4 (-63 % chroma, -28 % green: the stock RAW NR, same R/B > G pattern as §21b) => High turns RAW NR on at
8000. Maker note HighISONoiseReduction = "Off; Inactive" in both (stock High would record High): the capture side got
Off from the remapped property 0xdd. JPEG 100 % crop (work/films_v20/compare_iso8000_crop.png): High has less colour
blotching, luma grain still fine and unsmeared (no JPEG NR look); JPEG high-pass noise 4.1 -> 3.1 (20th pct), in line
with the RAW change alone. Not yet tested: High at ISO 2500 (should be off), Mid at 6400/8000, Auto (stock).
Resolution (same pair): image size unchanged (JPEG 6000x4000, DNG 6112x4064, crop 6000x4000). High-contrast edges
equally sharp: JPEG 10-90 % edge width, tape top edge 1.96 px (Off) vs 1.84 (High), window sill 5.93 vs 5.72 (within
measurement noise). Fine low-contrast texture (chair weave, basket mesh) is a little softer with High, as expected
from the RAW NR (work/films_v20/detail_{chair,basket,knot}.png); the two frames are shifted a few px, so this was
judged visually, not measured.
Test 2 (R0012074/75, ISO 8000 f/16, 1/5 vs 1/4 = +1/3 EV for 75, tripod, chair fabric filling the frame). 75 = High
(R/B var/mean 93 -> 46, 102 -> 73; texture-dominated, so raw_noise's flat-block numbers are rough here).
`nr_mtf.py` (new): per frequency band, signal = |sum over 64 px tiles of F(G1) conj F(G2)| (same scene, independent
noise), noise = rest of the green power; exposure-normalised to the first file. Signal High/Off by band (cycles per
green-plane px) 0.03-0.08 / 0.08-0.15 / 0.15-0.25 / 0.25-0.35 / 0.35-0.5:
  fabric pair 0.99 / 0.99 / 0.97 / 0.93 / 0.73, noise 0.90 / 0.90 / 0.88 / 0.81 / 0.76 (0.87 of that is the +1/3 EV);
  first pair (064/65, whole frame, equal exposure) 0.96 / 0.99 / 0.99 / 1.05 / 0.88, noise 0.85 / 0.74 / 0.73 / 0.73 / 0.73.
=> the PPU NR is texture-adaptive: in flat areas green noise -27 % (power), in dense texture only ~-10 %, and the
scene detail is kept up to ~0.35 cyc/px; only the finest band (near Nyquist, signal < 5 % of the noise there) loses
~12-27 % power (~6-15 % amplitude). JPEG crop (work/films_v20/detail_fabric_iso8000.png): weave equally resolved,
High has less colour speckle.
Test 3 (R0012076..85, fabric, f/16, tripod, High/Off pairs at ISO 3200/5000/8000/12800/16000, same exposure per pair;
High identified by R/B var/mean: 84, 83, 80, 76, 79). RAW NR on with High at all five ISOs incl. 3200 (R 52.7 -> 29.5).
Finest band (0.35-0.5 cyc/green px, nr_mtf box 600:3400,1000:5000) signal High/Off: 3200 0.80, 5000 0.82, 8000 0.59,
12800 0.71, 16000 0.50 (power; amplitude 0.89/0.91/0.77/0.84/0.71); noise 1.02/0.78/0.92/0.88/0.69. Signal there is
only ~4-11 % of the noise power, so these ratios are rough (and long exposures 1/8..0.6 s may add shake differences).
**JPEG remap failure:** R0012076 (High, ISO 12800, first shot of the session) has maker note "Strong; Active (Strong)"
and JPEG fine-detail std 0.32x of the Off shot (other pairs 0.88-0.91x = RAW NR alone): the capture side got the
unremapped High (3). Later High shots (79, 80, 83, 84) record Off. Likely a power-on / mode-entry sync of property 0xdd
that does not go through setter 0x53252aa0 (or the gate 0x53252a44 path). To find: other writers of the capture-side
value at startup.
Test 4 (R0012086/87, ISO 3200 1/4 f/16, Program, High-ISO NR = Mid, consecutive shutter counts 12125/12126; one shot
after selecting Mid, one after a power cycle - order per data below). RAW: identical (R/G/B var/mean 20.5/19.0/19.1 in
both) = Mid keeps RAW NR off at 3200, as intended. JPEG: 86 maker note "Medium; Active (Medium)", JPEG fine std 1.96
vs 2.86 for 87 ("Off; Inactive"). With test 3 (first shot of the session = Strong), 86 is the post-restart shot:
**after power-on the capture side gets the raw menu value, not the remapped one; selecting the value again fixes it.**
The power-on sync of property 0xdd bypasses the setter hook at 0x53252ACC.
Test 5 (R0012088/89/90, ISO 8000 1/10, High; 88 after selecting High, 89 after a power cycle, 90 after Off -> High).
RAW identical in all three (R/G/B var/mean 16.0/35.2/17.3: RAW NR on, chroma-heavy as usual) -> the RAW switch reads
the menu directly and survives restarts. JPEG: 88 "Off; Inactive" fine std 3.32, **89 "Strong; Active" 1.14**, 90 "Off"
3.33. Confirms: at power-on property 0xdd is synced with the raw menu value outside setter 0x53252aa0; re-selecting
the value fixes it until the next power cycle.

## 39. Films v21: RAW NR only from ISO 5000, JPEG NR = stock menu (built 2026-10-10, not yet camera-tested)
User, after the v20 tests (JPEG remap lost at power-on, §38a): drop the menu link; RAW NR on only at ISO >= 5000, leave
the JPEG NR setting stock. Built as v18 with `--raw-nr-above 4000` (same mechanism as v6/v7/v18, §21b/c: clear the
enable byte of the mode-0 NR B entries, both variants, index 36..75; first NR index 76 = ISO ~4500, so ISO 4000
(idx 75) off, 5000 (77) on). No code change, no menu hook, nothing lost at restart. Checked: only those 80 enable bytes
differ from stock, strengths and indices >= 76 identical; verify_slots18 ALL OK (114). v19/v20 menu hooks not included.
High-ISO NR menu = stock JPEG NR at every value (and does not affect RAW NR).
`work/films_v21/fwdc239b.bin` SHA-256 fba6a50c96d60eeebf55a4dcd261ab1c03886ef3b62ef872df7e95187e117708.

## 40. Films v22: Sony FL replaces Gold 200 (built 2026-10-10, not yet camera-tested)
User: replace Gold 200 with Sony's FL ("Film") Creative Look, as the Sony-A7V-Picture-Profile-Creator project uses it. That
repo only copies Adobe's Camera Matching DCPs, so the target is `Sony DSC-RX1RM3 Camera FL.dcp` (Adobe DNG Converter
18.7 payload, extracted without installing; work/films_v22/dcp). Gold chosen over HDR Tone: it frees its own knots and
sector block (HDR Tone frees no space, free space was 0), and Gold/Portra were already hard to tell apart (§24, photo-v13).
- DCP (new `dcp.py`): ForwardMatrix = ProPhoto->XYZ D50, no HueSatMap, LookTable 90x16x16 (value axis sRGB-encoded),
  256-point ProfileToneCurve, BaselineExposureOffset -0.35. With that ForwardMatrix the white-balanced CAMERA RGB is
  treated as ProPhoto, so the LookTable acts on sensor RGB: the bake maps sRGB D65 -> RX1R III RGB via ColorMatrix2
  (neutral -> 1,1,1), applies LookTable + RefBaselineRGBTone, reads the result as ProPhoto D50 -> sRGB (Bradford).
  (A first bake fed ProPhoto directly: Camera ST then turned skies purple, hue 253; with camera RGB ST sky = 215.)
- Exposure: -0.92 EV, where the same set's Camera ST puts 18% grey at GR Standard's 0.461 (as Classic Neg §22n).
  FL is then brighter than ST: grey 0.591 vs 0.461 at 0 EV, 0.821 vs 0.668 at +1, shadows -4 EV 0.007.
  FL vs ST (RX1R III): sky hue 215 -> 196 (cyan), foliage 91 -> 146 (teal), reds/wood/skin hue kept, more chroma.
- Fit (`work/films_v22/fit_fl.sh`, b4 n3 as Classic Chrome): Standard vs target 13.50 -> cube_fit chart 3.39 -> with
  sectors (refit22.py) general / warm / ColorChecker / camera chart 1.50 / 1.85 / 1.43 / 1.77 (other films 1.1-2.1).
  On real RAWs (preview.py, photo-v10 chart + photo-v13 scenes): model vs target 1.06 / 0.77 / 0.71 / 0.73 mean.
- Build: v21 command with `sonyfl=work/films_v22/fits/sonyfl.json` in gold's position (tone 27, legacy record slot,
  icon id, maker-note ImageTone code and slider storage all Gold's; name "Sony FL", icon 'FL'). make_slots22.py /
  verify_slots22.py = the v18 scripts + fl22.py registration. verify ALL OK (114). Free space unchanged from v21.
- Licence: the DCP, the cube and the fit are derived from Adobe profile data: personal use, keep out of the public repo.
`work/films_v22/fwdc239b.bin` SHA-256 045454f486bd9cac54273091eb7b2c1481d5f878e52367c005acc7a4b624d5aa.

### 40a. FL from other Sony bodies; v22b = A7 IV / A7C II FL (built 2026-10-10, not yet camera-tested)
Same bake (dcp.py, exposure from each body's own Camera ST) for five FL profiles. A7 IV and A7C II FL are byte-identical
(LookTable + tone curve); RX1R III, A7R V and A1 II each have their own. Mean / p95 dE2000 between the renders (4000
random colours + grey ramp): RX1R III vs A7 IV 4.36 / 8.78, vs A7R V 2.20 / 3.88, A7 IV vs A7R V 3.33 / 7.72, A1 II vs
any 6.4-9.0 / 18-25 (A1 II and RX1R III push foliage/sky to full chroma; A1 II needs -1.12 EV vs about -0.9 for the rest).
Greys agree (0 EV 0.589-0.591) except the deep shadows: RX1R III / A1 II -4 EV 0.007, A7 IV / A7R V 0.033 (milder toe).
A7 IV vs RX1R III: foliage hue 114 vs 146 at chroma 0.40 vs 1.00, sky 203 vs 197, skin/red the same. Because each
LookTable is built for its own sensor and the bake reaches sensor RGB through a 3x3 ColorMatrix, some of the spread is
the bake, not Sony; only real FL JPEGs can say which is closer.
A7 IV fit (fit_fl4.sh, -0.90 EV) fits the GR pipeline better: general / warm / ColorChecker / camera chart
1.48 / 0.87 / 1.17 / 1.44 (RX1R III 1.50 / 1.85 / 1.43 / 1.77); real RAWs 0.97 / 0.70 / 0.67 / 0.65 (RX1R III
1.06 / 0.77 / 0.71 / 0.73). preview_fl_variants.jpg: on the photo-v13 scenes the two look close; A7 IV greens and cyans
are less saturated and its shadows less crushed.
`work/films_v22b/fwdc239b.bin` (v22 with fits/sonyfl4.json) SHA-256 59abfe843ff22b3160cc5c81c7de901684e569970b920d3c30f85b65eea056d7, verify ALL OK.

### 40b. A7C II FL vs GR v22b on the same chart (photo-v22b, 2026-10-10); v22c / v22d
Hue chart on the monitor, A7C II (FE 20-70 F4, FL default sliders: EXIF Saturation +2, DRO Auto) ARW+HIF and GR III
v22b (ImageTone 270 = Sony FL) DNG+JPG; pair 1 Daylight WB (DSC06539 / R0012099, same light), pair 2 5500 K
(DSC06541 / R0012100, Sony -0.35 EV less light). work/films_v22b/pairs.py (patches 7x36, chart.py; HIF via sips -> 16-bit
TIFF, sRGB), mean dE2000 over ~218 patches:
| | daylight | 5500 K |
| GR v22b JPG vs Sony HIF | 7.83 | 7.45 |
| Adobe A7 IV FL (dcp.py) on the Sony's own ARW vs HIF | 2.82 | 5.67 (5.05 with free WB) |
| v22b model vs GR JPG (camera = model) | 2.45 | 2.39 |
- The Adobe A7 IV profile is a fair model of the real FL (RX1R III profile on the same ARW 4.38: v22b's A7 IV choice
  confirmed; extra chroma factor 0.98 => the +2 saturation is FL's default as Adobe profiled it). Real FL lifts deep
  shadows and rolls off highlights more than the DCP (HIF grey 0.026/0.206 vs DCP 0.005/0.135; DRO Auto may cause part).
- The two Daylight / 5500 K presets disagree on the monitor white (grey a* -10 / -13.5 GR vs -7 / -6 Sony): a WB
  calibration difference, not part of the look; handled as nuisance gains below.
- Exposure: neutral-grey link Sony scene / GR scene -> the GR-side bake should be -0.65 EV, not -0.90 (FL renders
  ~0.25 EV brighter than our Standard-matched assumption). Joint fit below gives -0.64.
- Rest = how the two chains see the monitor's saturated colours: GR v22b JPG chroma 30.6 / 32.2 vs HIF 27.6 / 25.4.
  work/films_v22b/fitC.py: one white-preserving 3x3 C (GR scene -> Sony scene) shared by both pairs, per-pair WB gains
  and exposure as nuisance: FL(C . GR scene) vs HIF 5.95 / 6.93 (C = I) -> 4.67 / 4.05.
  C = [[0.946, 0.282, -0.229], [0.142, 0.933, -0.076], [0.068, 0.14, 0.791]]. Monitor primaries are narrow-band, so C may be partly monitor metamerism (§27: reflective
  colours differ ~1 dE between sensors after a 3x3); needs a real-scene pair to confirm.
- v22c (fit_fl4c.sh, -0.65 EV, sonyfl4c: general/warm/CC/chart 1.51/0.90/1.11/1.53), v22d (fit_fl4d.sh, -0.64 EV +
  dcp.py --pre C, sonyfl4d: 1.75/0.72/1.24/1.99). Predicted GR JPG (camera JPG + new - v22b model, predict2.py) vs HIF:
  v22b 7.83 / 7.45, v22c 6.48 / 7.69, v22d 5.88 / 5.44 (chroma 23.6 / 24.4 vs HIF 27.6 / 25.4). Residual: WB preset
  difference, shadow lift, monitor colours.
`work/films_v22c/fwdc239b.bin` SHA-256 5ebb565f9851a9d17c0cf08ce7a58bc26376b2c0ed4810a9b425de49c919e88d,
`work/films_v22d/fwdc239b.bin` SHA-256 0dcda2da5cfabd72c51c347145793b2e623b4b9a6aac68c267c1ef0f101e2519, both ALL OK.

### 40c. Faster emulation (2026-10-10)
verify_slots22 took 309 s; profile: building ~62k Unicorn instances (17 MB ROM map + copy each, ~1.5 ms + teardown),
not the emulated code. emu.py: read-only ROM pages shared between instances (mem_map_ptr, per immutable bytes image;
guest writes fault, host writes to ROM assert), code hooks only on the stubbed addresses (was every instruction),
no read hook unless trace_ranges is used, no zero-fill of fresh heap, and Emu.reset() (RW data, dirty bss pages,
stack, heap) so one instance serves many calls; verify_slots18 reuses one Emu per image in path_of and per
(image, stub) in the "is active mode" site loops. verify 309 s -> 24 s, log byte-identical, still fails on a wrong fit.

Parallel (2026-10-11), 8-core Mac:
  * verify_slots18 --jobs N (default $VERIFY_JOBS, else CPU count up to 8): the stock image decodes in the parent while a
    forked child decodes the patched one (~3 s each, pure Python), then N forked workers split the emulated checks by
    named section (pipeline per stage and per film, MultiAxial per stage, adjustments, site checks per owner tone; cheap
    sections run everywhere, printed by one owner), longest first; the parent prints the lines in section order.
    Workers that skip a stage's stock part first render a film and then tone 11: R2Y 0x818F (already allowed to differ)
    stays set once a stock mode follows a film, and the film lines report it. 24 s -> 8.8 s; log byte-identical for
    --jobs 1/2/3/4/8 and on a wrong fit (11 FAIL lines either way); a crashing worker -> FAIL line + exit 1.
  * prun.py: runs shell jobs in parallel with dependencies (name < deps: command), one log per job in work/prun_logs/,
    skips the dependents of a failed job, shares the CPUs out through VERIFY_JOBS / BLAS thread variables.
    work/films_v22/jobs.txt = the four Sony FL fits and their builds: 196 s wall (772 s of job time; one after the other
    ~9.5 min), all fits and the four firmware files byte-identical to the sequential runs.
  * Still single-threaded: a fit chain (~90 s alone, ~125 s when four run at once) and make (27 s alone: the gr-custom-tool
    frame codec decodes three times, ~3 s each, and 300 assembler subprocesses); decode frames reference earlier output,
    so it does not split.

### 40d. Films v22e: logo icons (built 2026-10-11, not yet camera-tested)
Icons are 40x40 RGBA in the slots carved from the unused HDF / GR IIIx-cert image (§24), 6400 B each, so a logo costs no
space: only the pixels change. `logo_icons.py`: film-strip frame of 0xE8 kept, middle band = maker wordmark (rows
10-18, max 32 px wide) over the label (rows 19-30, DIN Condensed). Wordmarks from Wikimedia Commons PNG renders of
public-domain SVGs (Kodak 2006-2016 wordmark, Fujifilm (black -> white, red stroke kept), Sony without "make.believe"
(white), Ricoh 2005 for the GR IV Cinema looks), fetched into ../logos/src (`--fetch`). `make_slots22.py --logo-icons`
(M15.ICON_RENDER hook; without it v22d rebuilds byte-identical). v22e (work/films_v22e, SHA 9529c0b4...) = v22d with
only ICONBIN different; verify ALL OK, log = v22d's except the changed-byte count; each rendered icon found in the
decoded ICONBIN. Trademarks: personal build only, logo files/icons/build stay out of the public repo.

### 40e. Films v22f: package icons (built 2026-10-11, not yet camera-tested)
`logo_icons.render_package` (`make_slots22.py --package-icons`): each film icon is the front of its box at 40x40
(8x supersampled shapes, fitted text, the wordmarks of §40d; rounded corners, no film-strip frame). Layouts after Commons
photos of the boxes: Portra (yellow, violet speed panel), Ektar 100 (black, yellow Kodak band), Superia green with its
colour bar for Classic Neg; boxes in the maker's style for films without one (Vision3 250D/500T, Pro 400H, Classic
Chrome, Sony FL, Ricoh Cinema Yellow/Green). v22f (work/films_v22f, SHA 90a89e5f...) = v22d with only ICONBIN changed,
verify ALL OK (log = v22d's apart from the icon byte count), every icon found in the decoded ICONBIN. Personal build.

### 40f. Films v22g: box icons from photos of the real 35 mm boxes (built 2026-10-11, not yet camera-tested)
v22f's boxes were partly from memory and old photos (Portra = 2000s Portra 800 style, Ektar = pre-2025 black box,
Pro 400H invented). Redrawn from retailer product photos (logos/ref2, Analogue Wonderland Shopify product JSON):
current Portra 400 (yellow bands, blue-violet panel), Kodak Eastman Ektar 100 (yellow, red K square, black band, red
strip), Fujicolor Pro 400H (green band, violet, black band, cream text), Superia X-TRA 400 for Classic Neg, Provia 100F
style for Classic Chrome, VISION3 Super 8 box for Vision3 250D/500T. v22g (work/films_v22g, SHA 9eeec157...) = v22d with
only ICONBIN changed; verify ALL OK; compare.png = photo vs icon. Personal build.

## 41. gr-custom-tool 549591d / GR4-LUTSmith 2.1.1 review (2026-10-11, reading only)
- LUTSmith 1.7.0-2.1.1: Fitter / HueFitter / post_effective / hue_apply_q / HUE_SIGMA unchanged since 1.6.0, so §28a
  still holds (v16 ahead on 24/28 numbers). New: parallel turns (--jobs, helper processes, results identical to serial),
  a Pareto set of kept turns, shareable look.json (byte-identical rebuild), `check` (identify a firmware file: official /
  which slots carry looks, names, icons) and `selftest` (rebuild a bundled example and compare), multilingual slot
  names checked against per-language character sets.
- gr-custom-tool 549591d (GR IV): Adobe Look/Profile XMP -> target JPEG on the user's DNGs (LibRaw/OpenCV approximation,
  or Lightroom Classic via a plugin), 2 DNGs fitted + 1 held out; same resources as ours (s16 matrix, u16 gamma, s32
  MultiAxial). update_policy.py relaxes the GR IV CheckVersion gate 0x5383171C (8 branches) to allow older firmware, and
  the docs warn: **factory-reset the camera before flashing an older/stock firmware, or settings for features the old
  firmware lacks can hang the menu.** GR III needs no gate patch (version >= current, §8), but the warning applies to us:
  a saved Image Control tone 25+ (or Custom 1/2 holding one) under stock 2.10 is untested. Until checked, set Image
  Control to a stock mode in shooting and in C1/C2 (or reset) before going back to stock.
- Slots (gr4_editor/slots.py + native/registry_state.c, GR IV 1.11.10.7): **up to 16 new filters** (style ids 34+),
  each cloned from a factory filter, plus the 6 hidden Mono styles 25-30 unlocked. Each new filter gets its **own
  slider storage** (main/mirror/shadow + Custom snapshots, APData save/load hooks, per-slot defaults), and on load a
  saved selection whose style is no longer present resets to Standard (11). Ours (v13+) adds 6-8 entries and the
  appended films share Standard's sliders (§36): their per-slot storage is a lead if we want separate sliders per film.
- Space: gr-custom-tool **grows the RTOS image**. Code and tables are appended after its end (_Patch.append, address
  0x53000000 + len), and firmware.py re-encodes the container with a larger decoded size ("growth" repack). Per-filter
  slider state goes on the heap: the allocation size of an existing settings object (owner cell 0x550885B4) is raised
  and each filter gets 468 B in it (native_raw.migrate_raw_arrays). Their README says it is not yet verified on a
  camera. GR4-LUTSmith does not grow: it reuses fixed regions and refuses when they are full. For GR III, growth stays
  blocked on the open question in §23 (does BOOT load more than the stock RTOS section length?). Their growth repack +
  a GR IV report of it booting would be the evidence to look for.

## 42. Free space for growth: RTOS can grow ~15 MB (static analysis, 2026-10-11, not camera-tested)
Answers the §23 / §41 open question (does BOOT load more than the stock RTOS length?) from the code:
- **Updater** (running RTOS, FwPartition.cpp). Each update rebuilds the eMMC fw partition table from the new file's
  PARTPARA (`make partition table` 0x536299A8): StartSec[0] = PARTPARA word 0 (0x600), StartSec[i+1] = StartSec[i] +
  AreaSize[i]/512, LoadAddr/JumpAddr from the record. The section write (0x5362C830) only checks
  `StartSec[i] + sectors(DataSize) <= StartSec[i+1]` ("partition data [%d] size = %d is over!!") and stores the real
  DataSize. The decode buffer is allocated with the header's decoded size (0x5362BF4C), no fixed cap.
- **BOOT** (section BOOT, runs at 0x50B00000). Reads the 0x87-sector table to 0x50B70100 and loads RTOS with
  `emmc_read(StartSec, ceil(DataSize/512), LoadAddr)` (0x50B00CBC..0x50B00CF0), i.e. the stored size, no constant.
- **PARTPARA** records (16 B from +4: AreaSize, LoadAddr, ?, JumpAddr; section flags >> 16 = record index), GR III =
  GR IV for the first two: BOOT 0x70000 @0x50B00000; **RTOS 64 MB @0x53000000**; SRIC 64 KB @0x510E0000; SHELLCMD
  64 KB @0x510F0000; ICONBIN 24 MB @0x51600000; LINUX 32 MB @0x41000000; INITFS 128 MB @0x43000000.

| Section | Used | Flash area | RAM bound | Headroom |
| --- | --- | --- | --- | --- |
| RTOS | 0x10B55C0 (16.7 MB) | 64 MB | RW data at 0x55000000 (and the RX mapping ends 0x54FFFFFF) | **0xF4AA40 = 15.3 MB** |
| ICONBIN | 0x1181314 (17.5 MB) | 24 MB | 0x52E00000 | 6.5 MB flash; RAM tail 0x52781314.. is referenced (591 literals into 0x5278-0x52E0) -> not free without more work |
| SRIC | 0xC000 | 64 KB | - | 16 KB |

The RTOS tail 0x540B55C0..0x54FFFFFF: no MOVW/MOVT pair or literal in code forms an address there (the only movt hits
are conditional data words), and the MMU maps it read-only, so no CPU code writes it. Appended code/tables go at
0x540B55C0+ (after the .data LMA, which stays put), exactly like gr-custom-tool's `_Patch.append` on GR IV.
BOOT's eMMC read (0x50B03F54) splits counts above 0xFFFF sectors, so no 16-bit cap; the fw table has one bank in practice (bank byte 0x10 only ever set to 0, 0x5362C2B4), so there is no A/B fallback if a grown RTOS fails to boot.
gr-custom-tool's README/DEMO_RELEASE only say the whole public release is untested on a camera (offline checks only); nothing specific about growth. Still unproven: a camera boot of a grown image. Cheap check: a tiny growth build (e.g. 64 KB marker + one
relocated table read through it) + a SYS_md dump of the tail via the §22d script probe.

### 42a. Growth probe and films v23 (built 2026-10-11; camera: v23 boots and runs extension code, §42b)
Same reading of the updater/BOOT as above, reached independently (section loop 0x5362A4C4: type 2 = PARTPARA ->
table, type 4 -> partition = flags >> 16 -> 0x53629D58 -> 0x5362C82C, "write partition data NG!!" when over;
FwDecoder 0x5362BD44 compares header and footer fields only). With one fw bank (no fallback), the first camera test
must not depend on extension code, hence the probe.
Tools: gr3patch.Image.grow(n) reserves bytes after the RTOS image (inserted at build(), header length updated, frames
repacked with gr-custom-tool's growth codec); make_slots23.ExtSpace = every allocator falls back to the extension.
- **Growth probe** `work/probe_ext` (make_probe23.py): v22g + 4 KB extension holding only the first film's name text
  ("Portra EXT"); no code there. verify_slots23 (v18 checks on a grown image): all OK except the two name checks,
  which see "Portra EXT" from the extension (expected). SHA-256 74d8777bf57917a1dfda803c8b9bb0adc955725c1d3e7de0639c336a6451de91.
- **Films v23** `work/films_v23` (make_slots23.py): v22g + 64 KB extension + Gold 200 back (7th appended film, tone 31;
  the four replacing films move to tones 32..35). All ten legacy record slots were taken, so the three per-slot tables
  of the ctx fill (look records 0x55018D94, MultiAxial sets 0x55018CF0, YCbCr sets 0x55018E4C; each read only by the
  movw/movt at 0x536DC28C..0x536DC2A8) move to the extension with 32 entries; new slot 26 has its record in the
  extension (Classic Chrome lands there; Gold takes slot 9). Icon id 0x2A4 (Kodak Gold box icon). In the extension:
  the tables, slot 26's record, and what no longer fit the stock caves (MA make hook, RAW-dev conv/kind, shooting detail
  kind, ImageTone tables) - 0x394 of 0x10000 bytes used. verify_slots23 --v23 ALL OK (122), emulated over the grown
  image with the ROM mapped read-only (no write into the extension). SHA-256
  ec8898fd0d99e61946e9666791800564526fd9bdd2085c6692cc0379c36c28c3. Only after the probe passed: v23 runs extension
  code on every frame (MA make), so an unloaded extension would crash at start-up.

### 42b. Films v24: every film appended, data in the extension, stock modes back (built 2026-10-11, not yet camera-tested)
User: v23 looks good on the camera (so the grown section loads and extension code runs); move every custom film to the
new space. GR4-LUTSmith 2.1.1 checked first for its "new space / copied pipeline": it does **not** grow the RTOS
(make_firmware refuses edits outside the RTOS section and checks the section layout is unchanged). Its room is a pool
of dead data (hidden Grainy/HDR and, when unused, High Contrast data; 2.7-5.8 KB), and for the "extra" slots it gives
each slot private copies of the stage blocks (tone-curve set header + 256-entry curves, hue table + 8 links + header,
colour-after header + 10 links + 9 matrices) from templates and re-points that slot's three rows per stage, because
those blocks are shared between stock looks. Our films have done the equivalent since v13: own tone -> own record slot
-> own record (copy of Standard's) with own look matrix, curves (library slots 9-11 per call), MultiAxial set, YCbCr set,
CSP post matrix; only the slider storage is borrowed. So there is nothing more to copy; v24 just moves it all out:
- make_slots24.py (on make_slots23.setup, now parametric): all films appended, tones 25..35 (v23's tones kept), record
  slots 26..36 with records and matrices in the extension (per-slot tables 40 entries; legacy records 0..10 and their
  matrices stay stock), exact 256-entry curves for every film in the extension (make_slots15.CURVE_REGIONS), Cross
  Process's library curves 3-11 untouched and the ctx fill keeps its preset chain (make_slots15.CROSS_CHAIN, as v14).
  Movie list stock. Films share Standard's sliders (the four former replacements lose their own).
- Still in v13..v16 caves: code in the Cross "random" case / Box-Muller helper (unreachable) and the moved 10-bit MA
  table; overflow to the extension. Extension: 0x577C of 0x10000 bytes taken (17 KB curves, 4 KB data area), 42 KB free.
- verify_slots24.py --v24: ALL OK (112): every stock mode and sub-mode incl. Cross Process (x797 1/2) identical to stock
  in both pipeline stages, also right after a film; per-slot tables 0..25 stock; film records in the extension; curve
  error 1/16384 (exact); lists [23, 10, 23] with the stock movie list. make_slots23 (v23) still rebuilds ec8898fd.
- SHA-256 7c21583d1ecbfee5da7dfae3ffac31afad2b27a2fab7e4e8c61f7826e015b650. Before flashing: movie Image Control to a
  stock mode (v23's movie list held the four films).

### 42c. Films v25: five more appended films (built 2026-10-11, not yet camera-tested)
User: add Fujifilm Nostalgic Neg / Eterna / Velvia / Reala Ace and Leica Eternal. Sources:
- Fujifilm: `abpy/FujifilmCameraProfiles` sRGB cubes (CC BY-NC-SA 4.0), fitted as Classic Neg / Classic Chrome (§22n:
  srgb at -0.88 EV, boost 4 / neutral 3, joint_fit, lab_fit, hue sectors; work/films_v25/fit.sh, refit25.py).
- Leica Eternal: no open-source recreation exists; the target is Leica's own Look LUT (17^3, "Unique Leica Look
  ID: 6"). Leica data: **personal builds only; the cube, its fit and anything derived are not published.**
  It is a look applied on a finished photo, so cube_fit got in_cs `grstd`: target = cube(GR Standard rendering of L)
  (cube_fit.standard, the same model as the "Standard vs target" score). Result: a strong S-curve (Standard grey 118 ->
  123, -4 EV 11 -> ~2, cool shadows, warm highlights); on the GR it will be darker / harder than on a Leica if Leica's
  base rendering is flatter (unknown).
Fit scores general / warm / ColorChecker / camera chart (dE2000, with sectors, as stored):
| film | score | v15-style fit before sectors |
| Nostalgic Neg | 2.46 / 1.36 / 1.29 / 1.93 | 2.83 / 1.57 / 1.40 / 2.09 |
| Eterna | 1.16 / 0.91 / 1.14 / 1.05 | 1.38 / 1.04 / 1.12 / 1.13 |
| Velvia | 2.09 / 1.49 / 1.89 / 1.79 | 2.38 / 1.57 / 2.05 / 2.37 |
| Reala Ace | 2.15 / 1.64 / 1.64 / 2.04 | 2.71 / 2.03 / 2.12 / 2.42 |
| Leica Eternal | 0.42 / 0.43 / 0.44 / 0.47 | 0.47 / 0.47 / 0.45 / 0.53 |
On two real GR III RAW scenes (photo-v13 R0011936/38) model vs target 0.94/0.89, 0.38/0.39, 1.01/1.06, 0.83/0.73,
0.26/0.19 (work/films_v25/preview.jpg). Provia (= Standard, §22n), Astia, Pro Neg Std/Hi, Fuji Bleach Bypass skipped.
Build: films25.py registers names / labels / box icons (icons 0x2A5..0x2A9) and NSLOT 48; make_slots25.py =
make_slots24.main (refactored, v24 still rebuilds 7c21583d) with films25. Tones 36..40, record slots 37..41.
verify_slots24.py --v25 (implies --v24; tone scans now 0..47): ALL OK (142), lists [28, 10, 28], RAW dev 30/31 options,
every film MultiAxial = own sectors, stock modes identical. Extension 34.9 KB still free.
`work/films_v25/fwdc239b.bin` SHA-256 d43ac8faac919e5c95f12c55080e17106a827ee83025092e4b70c8e35e97bff5.

## 43. gr3-firmware-research-skill v0.1 (7c114f6) review (2026-10-11, reading only)
Knowledge-only skill (no builder, no addresses for most hooks) describing a six-slot build on the **same file**
(root SHA-256 d6a3c9c2..., = our fwdc239b.bin); their camera evidence is user reports, like ours. Lists our public repo
as closest prior work. Their namespaces: public tone 30..35 (we use 25..35), processing entry 26..31, menu rows 12..17,
DNG/maker-note ImageTone 0x10C..0x111 (**same code space as ours**: their tone 30 and our tone 25 both write 0x10C, so
film RAWs cross-open as the wrong look between the two mods), name ids 791..796 (21 languages), icon ids 671..676
(our Gold icon 0x2A4 = 676 is in that set). New vs our notes:
- **Persistence sanitizer.** Tones 30+ never reach the 0xB26 UserData record or U/BOX snapshots: every durable write
  maps custom tones to 11, the real selection lives in private files (`CFnSTATE`-style) + private Grain keys; damaged /
  missing private records fall back to Standard. Purpose: stock firmware after rollback only ever reads stock values.
  Ours stores tone 25+ raw at +0x1C2/4/6 (the §41 "select a stock mode before reflashing" caveat). Static-only on
  their side too; no on-device rollback test.
- **Per-slot sliders.** RAM banks at data+0xB28 + slot*60 + group*20 + field*2 (10 fields, 3 Image Control sets),
  allocation of the settings object extended to 0xB28 + N*60, serialised schema stays 0xB26. Ours share Standard's.
- **RAW development per slot.** RAW param object is a 0x800 heap allocation, params at +0x400, row stride 17, set stride
  340, 20 rows; RAW-dev enum 13 reserved, slots at 14..19. Ours: enum 13..18 and films use the as-shot cache entry 0.
- **Colour Grain.** Image Control param id 15, UI Off/weak/medium/strong = native 0/3/2/1, state SI+0x795, colour modes
  made grain-aware via enable/preparation seams of the monochrome grain engine; per-file in tag 0x0247 index 19, file
  encoding 0/5/3/1; one stock "exclusion vector" in the metadata encoder writes a fixed value for 8 colour tones.
  Grain edit page and sidebar read the same state. Addresses not published.
- **Playback DISP** per file: DNG code -> property 37 ordinal 13..18 -> display 30..35 -> name/icon; tag 0x0247
  idx 0..6 -> props 38..44, 9 -> 49, 10 -> 50; they add a 10th (Grain) row in prop 140 (obj+0x3BC). Our films'
  playback info screen is not checked yet.
- **Update gate** 0x536284E0 compares all four version bytes 02 0A 15 1B (+0x38 and +0x50), unsigned <, equality
  accepted (refines §8, which only had major/minor). Build timestamp string at +0x58.

### 43a. Second pass against v24/v25 (2026-10-11, reading + one scan, no camera)
Repo unchanged (still 7c114f6). What applies now that films are tones 25..40 / maker-note codes 0x10C..0x11B:
- **Their completion checklist vs ours.** Done in ours: shooting UI/name/icon, rendering, per-file identity (maker-note
  code, §34c), RAW-dev list / as-shot / rendering, remembered tone. Not done: per-slot sliders (all films share
  Standard's), rollback sanitizer, colour Grain, Playback info screen. Their playback identity goes through its own
  bridge (DNG code -> property 37 ordinal -> display tone -> name/icon), separate from the RAW-dev reader 0x535BF7A8 we
  patched, so our films' playback info page may show Standard or nothing; added as a check to the v24/v25 HOW_TO_TEST.
- **Code range.** They verified 0x10C..0x111 only and warn not to extrapolate; ours writes up to 0x11B (v25) and the
  reader/writer tables are emulated end to end (verify --v25), but any second consumer of the code (playback bridge)
  is unchecked. Test step: as-shot of a Leica Eternal DNG.
- **RAW-dev parameter cache.** They give each slot its own RAW-dev values by enlarging the cache (0x800 heap object,
  3 x 20 x 17); ours keeps the stock 3 x 13 x 17 cache and maps films to Standard's entry (§36), memory-safe at any
  film count. Their list capacity 21; ours 31 (option allocation follows the patched capacity, §34d).
- **Release scan.** Their tools/release_scan.py (MIT, stdlib, read-only) on gr3-film-mods-public HEAD 6326986 (git
  archive, history not scanned): no personal paths / emails / credentials of ours; 2 email hits are upstream addresses
  inside the spektrafilm licence text; 219 "numeric payload" hits are the published fit JSONs (intended). Usable as a
  pre-push check for the public repo.
- Still the best new-feature leads, in order: per-slot slider banks (+0xB28 + slot*60, matters more with 16 films sharing
  one set), colour Grain (param 15, SI+0x795), sanitizer for rollback. None has addresses published; each is our own RE.

## 44. Settings storage, stock with a film tone, plan for v26 (static + emulation, 2026-10-11; built as v26, §44a)
User: do the research-skill features in groups of 2-3 builds: colour Grain, per-film sliders, safe return to stock
(private file accepted), RAW-dev values per film, playback info. Grain default Off for every film.
- **Stock firmware with a saved film tone faults.** run_tuning on the stock image: tone 25 renders (= Negative record,
  13 bytes differ from Standard), tones 26..47 read records past the 26-entry table 0x55018D94 (pointers into other
  ROM tables) and fault at 0x536DF124 (unmapped read in emulation; on the camera that memory may be mapped, so garbage
  or a crash). Nothing found yet that clamps the tone on load. So after flashing back to stock with a film in a still
  set or in U1/U2/U3, live view is expected to break: the §41 "stock mode first" step is mandatory, not a precaution.
- **Settings files.** AppData (src/AppData.cpp) stores keys 0..11 as files `APData%02d.bin` (name builder 0x53826BDC,
  `cmp r1,#0xb`; write 0x53826C54 -> FS write 0x53825FA8(fs, name, size, src); read 0x53827218 -> 0x53825648; size
  0x538270BC; per-key byte at obj+0x10+key; delete-all loops over 12). Object = [0x53828014()+8], fs = [obj].
  Keys: 0 flag byte, 1 main user settings (0xB26 B), 2..8 seven more full records (table 0x53B59200; U1/U2/U3 / BOX
  snapshots), 9 version string (0x53B4EC18), 10 a 0x104C-byte table (0x53B593AC) compared word for word on load ->
  "Invalid user FwUp!!!!! Clear UserData" if different, 11 used by 0x532DC318.
  Save-all 0x5323F278 (writes keys 0, 1, 2..8, 9, 10; only writer besides a debug command 0x5304B2DC).
  Load 0x5324B288: records are heap blocks of 0xB28 B (alloc via vtable +8, sites 0x5324B338/0x5324B400/0x5324B4A4/
  0x5324B5B8/0x5324B6E0), defaults copied first (0x532406FC), then the file read with size 0xB28, per-record
  fix-up 0x53246DF8 (u16 fields: value byte + flag byte, copied only where the flag is set). Exit 0x5324B42C.
- **Standard's sliders** (bytes): set No0 +0x1C8 sat, +0x1D4 hue, +0x1E0 key, +0x1F2 contrast, +0x204 HL, +0x216
  shadow, +0x228 sharpness, +0x278 shading, +0x28A clarity; No1 = +0xE2, No2 = +0x1C4. Store functions = the callers
  of the 27 checks found by make_slots.check_sites(11).
- **Tone change**: store functions 0x5327B394 / 0x5327B3B4 / 0x5327B3D4 (`strb r1,[r3,#0x1c2/4/6]`, then apply-all
  0x532750F8), 13 callers each. Record copies elsewhere: 0x5326CC44 (field-by-field copy), 0x53246DF8 (load merge).
- Plan v26 (per-film sliders + safe return, they share the storage): RAM banks after the main record (allocation
  0xB28 -> 0xB28 + banks), swap on tone change (bank[old] <- Standard's 9 fields, fields <- bank[new]); save-all
  sanitises each record in place (film tone -> 11, Standard fields <- Standard's bank), writes it, restores it, and
  writes a private file (FS write with our own name, outside the APData key range) holding the film tones, film
  slider values per record, checksums of the sanitised records and the banks; load restores films only into records
  whose checksum still matches (stock changes win). v27: colour Grain + playback info + RAW-dev values per film.

### 44a. Films v26: separate sliders per film + safe return (built 2026-10-11, not yet camera-tested)
make_slots26.py (= make_slots24.main via the new make_slots24.EXTRA hook list, films25 registered; v24/v25 still
rebuild 7c21583d / d43ac8fa): `patch_persist` adds one 0x5F8-byte code block in the extension and patches 10 words:
- 4 alloc sites `movw r1,#0xb28` -> 0xB28 + 0x510: the main record's block carries the private area (= file image):
  header (magic 'GRF1', size, film count, checksum), 8 record entries (tones, film fields, the Standard fields that
  were written), 24 slider banks (Standard + tones 25..47) of [3 sets][9 fields].
- tone stores 0x5327B3A4/C4/E4 -> `bl swapN`: bank[old] <- Standard's 9 fields of that set, fields <- bank[new], for
  Standard and this build's films only; then the store.
- save-all 0x5323F274 -> save_hook: sanitise all 8 records in place, stock save (keys 0..10 unchanged), restore the
  records, write FILMDATA.bin with the stock FS write (F:\ + H:\DOMDTBK copy, the APData mechanism).
- load exit 0x5324B42C -> load_hook: read FILMDATA.bin; valid -> a set gets its film back only if the record still
  shows Standard with the exact Standard fields written; else banks re-initialised (Standard = current fields, films
  = factory defaults, all 4 = 0).
- reset 0x5326CC40 (Reset, shooting settings part) -> stock reset, then banks re-initialised.
verify: verify_slots24.py --v25 on v26 ALL OK (142); verify_v26.py ALL OK (30): fake model + stubbed AppData/FS,
swap per set, save = stock keys/sizes and byte-identical to stock without films, no film tone in any written
record, RAM unchanged after save, reboot restores main and U-mode films, stock-side tone or slider change wins,
damaged file -> Standard, v25 raw film tone kept, reset re-inits.
Not covered offline: the real FS (file creation, size, timing), the UI paths calling the tone stores, U-mode recall
on the camera (record memcpy, no swap: the recalled record brings its own film fields), concurrency during save.
Extension: 32.6 KB free. `work/films_v26/fwdc239b.bin` SHA-256
6f42232f1782b7d1f70721fd3058653cdac8fc17af6a409276487f6308b8e1db.

## 45. Films v27: Grain for the films, playback info, RAW-dev values per film (built 2026-10-11; camera: no grain, see §47)
make_slots27.py (= v26 + `patch_v27` via make_slots24.EXTRA; v26 still rebuilds 6f42232f). One 0x500-byte code block
plus tables in the extension (30.9 KB free after), 39 words patched.
- **Grain internals.** Grain is "Particle" in the firmware: native 0 Off / 3 Low / 2 Mid / 1 High (debug strings
  Off/Low/Mid/High). Record fields: Monotone/Soft/Hard/Hi-Contrast B&W No0 +0x29A..+0x2A0 (No1 +0x37C.., No2 +0xE2
  later), and a hidden one for **Negative Film** (+0xA54 No0): setter, default, apply-all and the pass-through all
  handle it, only the parameter list lacks it, so the Grain engine is not monochrome-only. Shooting state SI+0x795 =
  property 0xC3 (setter 0x5354C570, getter 0x5354A36C, validity 0x535542CC: value 0..3 and state+0x6C0 != 2, no tone
  check). SetParticle 0x532C1780 / GetDefaultValueParticle 0x532C9744 switch on tone 13..22 per set.
  Apply-all 0x532750F8 fills one struct (Grain at fp-0xB7, default 0; each "active" check writes its field) and
  pushes it as property 0x82 at 0x53279A0C. Pipeline pass-through 0x536DB7DC: Standard's case writes 0 to SI+0x795
  and ctx+0x1F8; mono and Negative cases pass SI+0x795 through. The UI current value is the live property.
- **Image Control parameter screen.** List table 0x53B3488C [set 0..2][index 0..11] -> (items, u16 count); item =
  (visibility, id): visibility 2 always, 0 not in RAW development ([obj+0x19D] = 1), 1 only there. Ids: 0 sat, 1 hue,
  2 key, 3 contrast, 4 HL, 5 shadow, 6 sharpness, 7 filter, 8/9/11 per-mode toning, 10/16 HDR, 12 toning,
  13 shading, 14 clarity, 15 Grain, 17 base (No1/No2). Index from GetBaseKindDetailControl 0x531ACA98 (films:
  v16's layout stub -> proxy = 0). Readers 0x531AFA10/0x531AFAB8/0x531AFF88/0x531B01D0 (`mla 12*set+index`).
  Same screen class serves RAW development, where Grain/Clarity are hidden for every mode.
- **v27 Grain:** films -> index 12 (0x531ACB1C bl -> own stub), table [3][13] with entry 12 = Standard's list of the
  set + (0, 15). Values per film and set in the spare bytes of the v26 banks (bank + 27 + set; v26 files: 0 = Off),
  so they are in FILMDATA.bin and never in the stock files; U1/U2/U3 use the film's current Grain. Default Off
  (3 default branches of 0x532C9744). SetParticle film branch: store, and for the active film (record set/tone, Grain
  settable 0x5324E000) set property 0xC3. Apply-all: 0x53279A0C -> hook writes the active film's Grain into
  fp-0xB7. Pipeline: 0x536DB800 -> films get a copy of Standard's case with `ldrb r6,[r3,#0x795]` and
  `strh r6,[ip]` (ctx+0x1F8) instead of the zeros.
- **Playback info.** Importer 0x535C24EC: maker-note ImageTone code - 0x100 <= 11 -> table 0x53D2DD64 -> property 37
  (1..12), else 0 (no Image Control shown: our film shots showed nothing). 0x532B44BC: ordinal -> display tone (table
  0x53B5CBC4: 11,12,10,14,15,16,17,8,19,20,21,22); icon 0x532B6EEC (u16 table 0x53B5B2F0 by display tone - 8);
  parameter rows 0x532B7CFC (switch on display tone - 8). v27: codes 0x10C+k -> ordinal 13+k -> display 25+k -> the
  film's box icon, rows = Standard's case. Also fixes earlier v24-v26 film shots (same codes).
- **RAW development values.** RawDevelopmentModel (0x3C4 B, inline in its parent; ctor 0x5327B948): cache
  +0x86 + slot*0xDD + entry*0x11, slot = Image Control set (selected slot +0x82, enum per slot +0x83..), 17 values
  indexed like the parameter ids. Init 0x5328993C: fill 0x53288E40 (each entry from that mode's shooting fields of
  the set, via 0x53286564), then the as-shot entry from SI (0x53289A3C). Selection 0x53289304 (slot, enum) and
  0x53289314 (saved). v27: banks [3][24][17] + owners after the v26 area in the main record block (allocation
  0xB28+0x510+0x4D0 = 0x1508, RAM only, magic 'RDB1'); fill hook builds every film's values from its own shooting
  sliders (live record fields for the active one, v26 bank otherwise); as-shot film takes the entry; selecting
  Standard / a film / "as shot" saves the entry to the previous owner and loads the new one.
verify: verify_slots24.py --v25 --v27 ALL OK (142; films' shooting layout = list 12), verify_v26.py ALL OK (30),
verify_v27.py ALL OK (51): list index and lists (stock unchanged, film list = Standard + Grain, hidden in RAW dev),
defaults Off without asserts, SetParticle (bank per set, property only for the active film / when settable,
Monotone stock), apply-all hook, pipeline (films keep SI+0x795, Standard 0, Grain Off output = v26), playback
(stock codes unchanged, films -> ordinal/display/icon/rows), RAW-dev (init from shooting sliders, swaps, saved
selection, as shot, enum outside -> untouched).
Not covered offline: the Grain effect itself (DSP, DF_EX.bin), the screens, the maker-note Grain field (a playback
Grain row is not added). `work/films_v27/fwdc239b.bin` SHA-256
6e11b3df120377e3954f66a06b93f1c332840361fd76ff0c0956f044f2b68943.

## 46. Films v28: Grain in the file / playback row, Grain in RAW development (built 2026-10-11; camera: grain recorded, not applied, §47)
make_slots28.py (= v27 + `patch_v28` via make_slots24.EXTRA; v27 still rebuilds 6e11b3df). 420 B of code in the
extension (30.5 KB free after), 4 words patched, 3 list bytes changed.
- **Grain in the file was already there in v27 (stock code, correction of §45).** Maker-note tag 0x0247 (44 B, 22 s16)
  is built by 0x535C81CC; bytes 38..41 come from 0x535C67D4: low nibble = Grain file code via the vector 0x5534AD18
  (native 0/1/2/3 -> 0/1/3/5, i.e. Off 0, High 1, Mid 3, Low 5) unless the tone is in the exclusion vector 0x55357B08
  (11 Standard, 12 Vivid, 17..22; built by 0x535CA050 from 0x53D2DE10) -> 8 = none. Films (25+) are not excluded, so
  every film shot since v24 records SI+0x795 (v24..v26: always 0 = Off). Readers: DNG / RAW development 0x535C1158
  (code -> SI+0x795, any tone, 8 leaves it), playback 0x535C3BC8 (code 0/1/3/5 -> property 0x33 = 1 Off / 2 High /
  3 Mid / 4 Low, else 0). Index 17 (bytes 34..37, 0x535C65A8) is the same pattern for another field.
- **Playback Grain row.** The row builder keeps 10 std::function slots (storage fp-0xD0 + 16k, manager +8, invoker
  +12; shared manager 0x532B576C / invoker 0x532B57F0 at fp-0x110 / fp-0x10C; closure = {row fn, 0, context sb}).
  Stock Grain row 0x532B5698 (Monotone cases): property 0x33 -> '--' / '3' / '2' / '1' (High..Low), icon 0x1DE;
  same guards as Clarity. Standard's case fills 9 slots and clears slot 10 at 0x532B81C8 (also reached from case 21).
  v28: 0x532B81C8 -> `gr_row`: display tone (fp-0xF5) 25+ -> context back from slot 9's closure (+8), slot 10 filled
  with the Grain row exactly like the stock blocks (template = stock shading block, checked word for word), then the
  row loop 0x532B81F0; anything else -> the stock clear.
- **RAW development.** Adjustable flags 0x53B5A750 [13 enums][17]: Grain (15) is 1 for enums 3..7 (the monochrome
  modes and Negative Film) and 0 for Standard, whose row the films use (v18). Grain getter 0x53284480 (no flag),
  setter 0x5328843C, apply 0x53288390 (enum 0 = as shot -> SI+0x795; else flag -> entry value -> 0x535597BC). The
  as-shot entry builder 0x53284EA8 takes value 15 from the file's Grain. v28: film lists' Grain item visibility
  0 -> 2; setter / apply entry -> film enums (13..12+n) store / apply entry 1's value 15 (the per-film entry swapped
  by v27); init hook (wraps v27's) sets every film's value 15 from its shooting Grain (bank + 27 + set, >3 -> Off) and
  the owner's into entry 1.
verify: verify_slots24.py --v25 --v27 ALL OK (142), verify_v26.py ALL OK (30), verify_v28.py ALL OK (75 = 24 new + the
51 v27 checks with the films' Grain shown in RAW development): row template, v27 -> v28 diff (4 hooks + 3 list words),
maker-note Grain for stock tones unchanged and for every film 0/1/3/5, DNG and playback read-back, slot-10 hook
(film / other tones, old content destroyed), Grain row text through the stock invoker, RAW-dev setter / apply / getter
(stock enums identical to stock, films per slot), init from the shooting Grain, selection swap.
Not covered offline: the screens (the 10th playback row on the real layout, the Grain item in RAW development), the
Grain effect itself. `work/films_v28/fwdc239b.bin` SHA-256
f6c3eb0fb91077dfc12b1afd831b944b8b7b09e4e8c93f7d5f126fad48576abf.

## 47. Camera: film Grain recorded but not applied; the effect-stage gate; films v29 (2026-10-11; camera: grain visible, §48)
User, photo-v28 (v28, Portra tone 25, ISO 8000): R0012172 Grain Off, R0012173 Grain High. Maker note 0x0247 byte 38 =
00 / 01 (recorded correctly), but no grain by eye and the same fine-detail noise (Laplacian std 3.16 vs 3.13). User saw
no grain in v27 either.
- **Cause: processing-plan gate.** 0x53513504 builds the shot's processing plan; 0x535131C0 sets plan+0x24, the stage
  that applies Shading (SI+0x793), Clarity (SI+0x794) and Grain (SI+0x795) (parameters 0x53503054: p+0 Shading table,
  p+2 Clarity, p+4 Grain native 1/2/3 -> 3/2/1, p+6 SI+0x796, p+8 float; ARM Granulation 0x5367AD3C, amplitude
  0x100/0x80/0x40 by p+4, in the stage at 0x53680DC0), by tone: 11 / 12 / 17..19 / 21 -> Shading or Clarity != 4
  (4 = 0); 13 / 15 / 16 / 22 -> Shading, Clarity or Grain (0x53513240); 14 -> always; 20 -> SI+0x796 != 0;
  anything else -> 0. Films (25+) got 0: their Grain (v27/v28) and their **Shading / Clarity sliders (since v13)** were
  never applied. v27's pipeline check only looked at the tuning field (obj+0x1F8), which is set for films; it did
  not cover this gate.
- **v29** (make_slots29.py): default `mov r3,#0` at 0x53513210 -> stub: tone 25..25+n-1 -> the Monotone rule
  0x53513240, else stock. One word patched, 20 B of code.
verify: verify_slots24.py --v25 --v27 ALL OK (142), verify_v26.py ALL OK (30), verify_v29.py ALL OK (80): gate on
stock vs v29 over tones 0..22, 25..41, 60 and Shading / Clarity / Grain combinations (stock tones identical; films 0
before, = Monotone after), v28 -> v29 diff (one word outside the extension), the v28 and v27 suites.
Not covered offline: the stage itself on a colour film image (it runs on the ARM, but needs the capture buffers).
`work/films_v29/fwdc239b.bin` SHA-256 3e52df7bfc0ca87fe854a4466a4c2fe959a216533192975d4d10befe6d057840.

## 48. Camera: v29 grain visible, no Grain item in RAW development; films v30 (2026-10-11, not yet camera-tested)
User: with v29 the grain now shows on film shots (the §47 gate fix works), but RAW development has no Grain item.
- **RAW development has its own parameter list table** 0x53B3476C [set 0..2][kind 0..11] -> (u8 parameter ids,
  count) (no visibility byte; set 1/2 lists start with id 17), read by 12 functions in 0x53190268..0x531922F4 (each
  `mov X,#0xc ; mla 12*set+kind`) and a max-count loop 0x5318E1BC (rows 0x60, end 0x120). Kind = +0x19B of the
  screen, set = +0x19A, from its own GetBaseKindDetailControl 0x5318DEA0 (v16 stub: films -> proxy -> Standard's 0).
  Stock Monotone kinds 2..5 do list Grain (id 15) there - correction of §45 ("not in RAW development for any mode"
  was read from the shooting table's visibility, which the RAW-dev screen never uses). v28's visibility change on
  the shooting film lists therefore had no effect on RAW development.
- **v30** (make_slots30.py): RAW-dev table [3][13] in the extension (entry 12 = Standard's ids + 15), the 12 readers
  repointed with stride 13, the max-count loop 0x68 / 0x138; 0x5318DEA0 -> stub: films -> kind 12, else v16's stub;
  shooting film lists' Grain item back to visibility 0 (as Monotone). 41 words patched outside the extension.
verify: verify_slots24.py --v25 --v27 --v30 ALL OK (142; RAW-dev layout of films = 12), verify_v26.py ALL OK (30),
verify_v30.py ALL OK (88): RAW-dev kind (stock tones unchanged, films 12, v29 0), readers / table / loop decoded,
stock kinds unchanged, films = Standard + Grain per set, v29 -> v30 diff, the v29 gate checks and the v28 / v27 suites.
Not covered offline: the RAW-dev screen drawing. `work/films_v30/fwdc239b.bin` SHA-256
ecdf9866800b4e40b1f716d10e81b303485d8d7aa61ee15e29223195f2b286fe.


## 49. Autofocus: structure, low-light behaviour, levers (static, 2026-10-11)
User: AF is slow, worst in low light; hardware limit or software? Static reading only, nothing patched.
- Two engines (src/ class names): **ZAF** = on-sensor phase detect (ZafCorrelation, ZafDefocus, ZafReliability,
  ZL/ZR line pairs, "ZAF_SEARCH_START") and **CAF** = contrast scan (CafProcess / CafDetection / CafWobbling,
  "CAF_SEARCH_START", search path, step width, quadratic peak fit). Hybrid: ZAF gives defocus + reliability; low
  reliability -> contrast scan (FarEndPointState / SearchFarDir / ElegantQuickSearch). AeInterfaceService also sets
  aperture / ND for contrast AF (SetContrastAfAperture / SetContrastAfNdFilter) and there is an AE-for-assist-light step
  (MSG_ID_LOCAL_FE_LV_START_AE_FOR_AF_ASSIST_LIGHT_REQ, AfAssistLed; user setting StillAfAssistBeam).
- **Sensor drive mode during the contrast scan** = CAF obj+0x1022, 0 High / 1 Middle / 2 Low / 3 SuperLow, chosen in
  0x533F4A70 (args: this, evaluate, default). It reads a 0x58-byte AE struct (AeInterfaceService 0x53492888 allocates it,
  sends it to CAF once as message 0x60C40809 -> setter 0x533F3F5C -> obj+0xFCC): u32 t[0..3] compared with 0x7FFFF and
  byte +0x54 vs a CAF count. t[0] <= 0x7FFFF -> High; otherwise Middle, Low or SuperLow as t[1] / t[2] / t[3] exceed it.
  So in dim light the scan runs at lower frame rates (longer exposure per frame), and each contrast sample takes longer.
  Meaning of t[] not decoded (AE fills it via commands 0x20000001/2 to [AeIf+0x50]). Frame rates per mode not decoded
  ("lVsyncTimeUs 200fps Equivalent 4997us" fallback; CafFlameRate float = sensor info +0x18 -> CAF +0x390).
- Debug override (RAM, until power-off): shell `CAF_Debug` (0x53017958): AllOff, InfocusTimeMeasure, PintShift,
  CisDriveModeFix, YDivCoefMeasure, JointQuickReturn, MovieLensDebug, ContrastH1Data, SaveDebugFile, TestTrace, GetKfp,
  DispCurrentState. `CAF_Debug CisDriveModeFix on CAF H|M|L|SL` (0x5341768C / 0x534174B8) sets +0x16D88/89/8A, which
  0x533F4A70 obeys (fixed mode); `... on LV` keeps the live-view mode during AF (0x533F70A4).
  `EnableAfDebugDataSave <0/1> [P/C/Z/O]` (0x53017778, flags +0x27..+0x2A of singleton 0x5506B56C). The store path
  0x536955B4 (called from 0x536972BC) writes per shot C:\LVAE%04d.txt, C:\CAF%04d.txt, C:\AF%04d.srm, C:\Ref%04d.txt
  (and C:\SR%04d.bin); the CAF dump prints VsyncTimeUs, IntegTimeUs, Gain, CafFlameRate, CafStepWidth, lens pulses,
  contrast H/V curves, ZAF reliability / direction. Shell focus_spd / focus_vol are stubs.
- Levers, in order of risk: AF assist light (user setting); drive-mode thresholds (faster scan, but shorter exposure per
  frame -> more gain -> noisier contrast -> more misses: the stock trade-off); step width / search path; ZAF reliability
  limits. Which one is the bottleneck is not known without measurements.
- Probe: `work/af_probe1/` (script only, no firmware change): `EnableAfDebugDataSave 1 P C Z O` at power-on; shots in
  bright / dim / dark light should leave the debug files. Not yet run.

## 50. Films v31: 4:3 and 16:9 aspect ratios (built 2026-10-11, never flashed; superseded by v32, §51)
User: "add 5:4, 4:3, 65:24, 16:9 to the ratio". Only four aspect ids exist (0 3:2, 1 4:3, 2 16:9, 3 1:1; §35), so
v31 adds the two that are native and leaves 5:4 / 65:24 for a decision (see below).
- UI setting = still settings [0x5320b31c()+4]+0x4c2, getter 0x53245260 (9 callers: menu text 0x531978a4, order
  checks 0x531a1230 / 0x531b8310, toggle 0x53227140, 0x5328d8a4, AF 0x532afc08 / 0x532afe40 / 0x532afe70, debug
  print 0x53366b78), setter 0x532525a4 -> capture property 0xd4 (0x5354c8e4; second sender 0x532580c4; apply-all
  reads +0x4c2 at 0x53279c54). Capture side: CommonProperty +0x7b6 (setter 0x5355a464, validity 0x5355445c: 0..3
  allowed unless state+0x6c0 == 2, other values pass). ~37 code readers of +0x7b6 (GetResolution 0x536a2a30 and its
  15 callers, DigitalFilter, StoreImage, playback ExtractImageAspectRatio 0x535ed43c, RAW-dev conversions).
- Stock already handles ids 1/2 in GetResolution (4:3 L 5328x4000, 16:9 L 6000x3376), nails, playback, Crop,
  Resize and DigitalFilter. Stock **asserts** for ids 1/2 in: AF GetSelectableFocusArea (0x532afc30) and the two AF
  area-size functions (0x532afe98 / 0x532afec4), and RAW-dev as-shot conversion (0x53289b0c).
- v31 (make_slots31.py): menu as make_aspect.patch_menu (counts 4, order 3:2 4:3 1:1 16:9, 7 order refs, toggle),
  strings "4:3" / "16:9" = ids 0x390 / 0x391 appended to the film string entries (getters' cmp 16 -> 18), stock icons
  0x153 / 0x151; AF ids 1/2 -> the 3:2 values (x 80..640, y 60..420; 560x360 / 336x216, inside both frames);
  RAW dev = make_aspect.patch_rawdev (3:2 RAW -> 3:2 / 4:3 / 1:1 / 16:9; 4:3 / 16:9 RAW keep their ratio).
- verify_v31.py ALL OK (only expected words changed, GetResolution identical to v30 for all ids, menu / toggle /
  names / AF / RAW dev); verify_v26 ALL OK; verify_slots24 --v30: only the 2 expected string-getter FAILs (it sees
  id 0x390); verify_v30: only its v29->v30 word-diff check fails (v31 words are extra). Live-view framing for 4:3 /
  16:9 not checked offline. Before returning to stock: aspect 3:2 / 1:1 (stock AF asserts on 1/2).
- 5:4 and 65:24 on top: need ids 4/5 through every +0x7b6 / getter consumer (switches with asserts on unknown ids,
  property validity, playback ratio detection, maker note / DNG crop, RAW-dev enums), or a "variant" byte that the
  v17 geometry patches consult; CommonProperty has no spare byte near +0x7b6 (0x7b0..0x7bf all used), and capture,
  playback and RAW development each need their own variant source. Not started.
`work/films_v31/fwdc239b.bin` SHA-256 2a9d2b4cc3ad2885eb81fd6f76735a8b0588a0e0a7f00a815ec7dc6e46c0f1d6.

## 51. Films v32: aspect ratios 3:2 / 4:3 / 5:4 / 65:24 (built 2026-10-11; camera: wrong live-view ratio + flicker, superseded by v33, §52)
User: "replace 1:1 and 16:9 with 5:4 and 65:24". Ids: 0 3:2, 1 4:3 (stock geometry), 2 65:24 (v17 XPan geometry),
3 5:4 (new, on the 1:1 id: same heights, width 5/4). Menu 3:2, 4:3, 5:4, 65:24. **Supersedes v31** (do not flash v31):
the survey for v32 found two places v31 left wrong for 4:3 / 16:9 (below).
New findings (static + emulation):
- **Pipeline row 0x536a3200**: id 0 -> row 0, id 3 -> row 1, ids 1/2 assert (non-fatal: 0x536B93D0 prints and returns, §23) -> row 0. Nine
  capture-side process functions (0x5350014c, 0x5350020c, 0x53501ad8, 0x53507168, SetupSroConfig 0x5350a058,
  0x5350a41c, 0x5350ca00, 0x5350cb18, 0x535256cc) index [row][crop] config tables with it (pointers to structs with
  sizes at +6..+0xc). Row 1 = the square configs, too small for 5:4 -> v32 returns row 0 for every id (as stock did
  for 4:3 / 16:9, minus the assert).
- **Display rect 0x535ee894** -> SI-like obj [+8]+0x6a0 (w, h, x, y in px << 12 on the 720x480 screen) per aspect and
  crop 1.0 / 1.25 / 1.78 from a RAM table filled by 0x535f4910 (3:2 0x55357d40/7e24/7e78, 1:1 7d60/7da0/7e88,
  16:9 7e98/7d00/7dc4 = **all zero** in GR III; 4:3 = not written). Probably the live-view / review frame. v32 stub:
  3:2 stock, 4:3 / 5:4 / 65:24 from own tables (3:2 rects scaled, centred).
- Maker-note AspectRatio code: ExtractImageAspectRatio 0x535ed43c maps 0 -> id 1, 1 -> 0, 2 -> 2, 3 -> 3 (Pentax
  codes 4:3 / 3:2 / 16:9 / 1:1). Unchanged: 5:4 files carry "1:1", 65:24 files "16:9"; they read back to the right id.
- Live view itself is processed as 3:2 (LiveViewProcessRecipe / VirtualWindowInfo call GetResolution with id 0).
- UI still settings [+4]+0x7b6 (getter 0x53245f88) is an unrelated setting with the same offset (GetStyle 0x5317877c).
v32 patch list: make_slots32.py docstring. Emulated: verify_v32.py ALL OK (changed words only at the listed sites;
GetResolution 3:2 / 4:3 = v30, 65:24 6000x2216 .. 1920x712, 5:4 4992x4000 / 4000x3200 / 2800x2240 / 1600x1280 for
every size and crop; row 0 for every id; nails; display rects; ratio + size class for all 40 sizes both orientations,
old 1:1 / 16:9 sizes rejected; Crop frames; Resize; menu / toggle / strings / icons; AF; DigitalFilter crop exact;
RAW dev 3:2 -> 3:2 / 4:3 / 5:4 / 65:24). verify_v26 ALL OK; verify_slots24 --v30: 3 expected FAILs (string ids
0x390+, ICONBIN change = only icons 0x100 / 0x151); verify_v30: only its v29->v30 word-diff check.
Not covered offline: what +0x6a0 drives on screen, JPEG / DNG encode at 4992 / 1600 widths, playback display.
Before returning to stock: aspect 3:2 (stock asserts / wrong geometry on 1 and 2; id 3 would become 1:1).
`work/films_v32/fwdc239b.bin` SHA-256 d5a9ff9d59226bd39ca3d0f254a9ec929860d2be1a3b62b1d31a6cea84600242.

## 52. Camera: v32 live view wrong ratio and flickering; films v33 open-gate live view (built 2026-10-11, not yet camera-tested)
User (v32 on the camera): "preview ratio is not correct, the screen is flicking"; asked to follow GR4-XPanUnlock
(GR4-XPanUnlock, GR IV 1.11, 2.0.0). How XPanUnlock does it (decoded with its own tool, RTOS payload offset
0x17D10 = 0x53000000): GetLiveViewStillAspect (LiveViewResolutionManager.cpp, 0x5388C7B8) maps aspect 0/1/2/3 to
live-view mode 0/2/1/3 (3:2 / 4:3 / 16:9 / 1:1 windows); XPanUnlock points all four jump-table cases at mode 0
(open gate) and replaces the live-view grid layer's draw (vtable 0x53E98C24 -> 0x53578848) with a stub that draws
the grid and then 4 fills per aspect via the camera's fill routine 0x5323C588 ({ctx, x, y, w, h, colour}; 16 = half
dim, 2 = white): two dim bars + two 2 px edge lines on the 720x480 screen. LiveViewController: grid off -> grid mode 2
(no lines, frame only) and the layer shown; grid on -> mode + 3.
**Cause in v32:** GR III still has the GR IV switch: 0x53669424 (and 0x53437174) map CommonProperty +0x7B6 via
tables 0x53D553C8 / 0x53C1CDCC (02 01 03) to live-view mode 2 / 1 / 3; the GR III window code 0x53666330 implements
only mode 3 (square). So v32's 4:3 / 65:24 ran half-configured 4:3 / 16:9 modes (flicker) and 5:4 got the 1:1 window.
(The +0x6A0 rect of §51 is the AF / touch image area, not the live-view window: GR IV keeps the same aspect rects,
640x480@40 for 4:3 etc., with XPanUnlock's open gate; read by 0x535BF7F4 AF frames, 0x532B12F0 touch mapping.)
GR IV -> GR III addresses: grid draw 0x5339C3B0 (vtable 0x53C0AAB4), base draw 0x533AB9BC, grid set 0x5339C340, UI
root / settings / aspect 0x5320AD88 / 0x5320B31C / 0x53245260, gfx 0x5320804C / 0x532081EC, fill 0x53208A2C
(200 instructions identical to GR IV's), LiveViewController 0x53177518 (grid off beq 0x53177580 -> 0x53177530,
join 0x53177534; grid set bl 0x531775D0).
**v33** (make_slots33.py = v32 + patch_lv): both mode tables -> 00 00 00; grid draw stub + grid on / off hooks as
XPanUnlock; frames 4:3 x 40..680, 5:4 x 60..660, 65:24 y 107..373 (crop-independent, as XPanUnlock). verify_v33
ALL OK (only the 5 live-view words change below the extension; 0x53669424 returns 0 for every id, v32 0/2/1/3;
draw stub per grid mode 0..4 x aspect; hooks). verify_v32 on v33: only its changed-words check fails (the 5 new
words); verify_v26 ALL OK. `work/films_v33/fwdc239b.bin` SHA-256 8ab90008f589cd3f1e105151748bec5e84db3f00a6d15be427b81d46b7b873e2.

## 53. Films v33b: Sony FL from the black-box a7C II model (built 2026-10-12, not yet camera-tested)
User: "replace the FL filter with this more accurate one" (on v32; built on v33 because v32 must not be flashed, §52).
- **Target.** `sony/sonysim.py` (method in `sony/A7C2_FINDINGS.md` §13). It is a 33^3 LUT: Sony scene-linear
  Rec.2020 (as-shot WB, 1.0 = raw white, log2 shaper) -> FL sRGB. It was fitted directly on the camera's own FL
  rendering, the full-size JpgFromRaw that each ARW embeds (= the HIF to 0.5 dE), of photo-v22b DSC06539 / DSC06541.
  No Adobe data is involved.
  - Fit: registration, flat pixels, trilinear least squares with a Laplacian prior, plus a grey-axis prior (weight 10).
  - Why the grey prior: the monitor grey is never neutral in either shot (R/G 0.84-0.86), so without it the true
    neutral axis was extrapolated (chroma up to 3.2). With it: <= 0.1, at an in-sample cost of 0.47 -> 0.49 dE.
  - On the Sony's own ARW vs HIF (chart patches): 0.57 mean, against 2.82 for the Adobe A7 IV DCP (§40b).
- **Link** (`work/films_v33b/link_bb.py`, as link2.py): both scenes are neutralised on the mid-grey ramp. The exposure
  comes from grey Y: model input = 0.504 x Rec2020(GR L), so GR grey 0.18 -> 0.0907 (-3.46 EV re raw white).
  It is baked as an sRGB-input cube for cube_fit (`sonyflbb_sRGB.cube`). No C matrix: the variant with C (sonyflbbc)
  scored 6.33 / 4.69 below, with chroma 21 vs HIF 26-28, so C desaturates.
- **Fit chain** `work/films_v33b/fit_flbb.sh` (cube_fit b4 n3 -> joint_fit -> lab_fit -> refit33b.py sectors), as
  fit_fl4d.sh.
  - GR model vs target, general / warm / CC / camera chart: 3.00 / 2.32 / 2.07 / 2.66 (sonyfl4d 1.75 / 0.72 / 1.24 /
    1.99).
  - The target is harder to express because it is non-smooth where the training charts never reached (it is
    extrapolated there).
  - On real GR scenes (preview33b.py, photo-v10 chart + photo-v13): GR model vs target 1.84 / 1.04 / 1.03 / 1.02;
    old FL vs new FL about 3.6 dE.
- **End to end** (predict33b.py = predict2.py; predicted GR JPG vs Sony HIF, mean dE2000, daylight / 5500 K):

  | fit | mean dE2000 | chroma (HIF 27.6 / 25.4) |
  |---|---|---|
  | sonyfl4 (v22b) | 7.83 / 7.45 | |
  | sonyfl4d (v33) | 5.88 / 5.44 | 23.6 / 24.4 |
  | sonyflbb (v33b) | 5.82 / 5.57 | 25.9 / 27.3 |

  Grey ramp G, daylight: v33b 0.06 / 0.47 / 0.78 / 0.86 vs HIF 0.07 / 0.49 / 0.79 / 0.87 (v33 0.04 / 0.40 / 0.80 /
  0.89). So tone and chroma are clearly closer and mean colour error is equal. The rest is the two sensors seeing the
  monitor's narrow-band primaries differently, common to every fit; this chart cannot separate it from the look.
- **Build.** `work/films_v33b/build.sh` = v33 command with sonyfl -> work/films_v33b/fits/sonyflbb.json; toolchain
  rebuilds v33 byte-identical (8ab90008).
  - verify.sh: film suite on v33 and v33b with each one's film list: same 3 expected FAILs (icons, two string-getter
    lines), the logs differ only in the two Sony FL R2Y lines.
  - verify_v26 ALL OK.
  - verify_v33 vs v32: its one changed-words check fails on 27 extra words 0x53dc2d38..0x53dc2da0 = Sony FL's
    MultiAxial sector data in the pre-extension cave (film suite: "MultiAxial = own sectors" OK). Expected.
- **Open.** The black-box target is least certain in deep shadows and outside the monitor gamut (preview: the target
  shows a red cast on the near-black chart surround; the GR fit mostly ignores it). More A7C II FL ARWs of real
  scenes (DRO Off) -> refit lookfit -> rerun fit_flbb.sh + build.sh.
`work/films_v33b/fwdc239b.bin` SHA-256 5f39a83634c52dcdcbdeb7ee78d50ddb99afdfa73903359ece62e9ceee92cac0.
