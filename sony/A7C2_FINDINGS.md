# ILCE-7CM2 (a7C II) v2.01: still-photo processing pipeline

> Published with the GR III notes because the GR III "Sony FL" film (`../FINDINGS.md` §40, §53) is fitted from
> this work. Firmware analysed: Sony ILCE-7CM2 update 2.01 (not included). [I] marks inferences.

Source: `BODYDATA-a7c2-2.1.DAT` (1,139,929,560 bytes), unpacked with this
repo's `fwtool.py unpack`. Analysis date: 2026-10-11.

**Method.** This is static analysis only. Every binary is stripped (`appFw.so`
exports exactly one symbol). The findings come from C++ RTTI type names,
`__FILE__` strings, log/format strings, AXI/clock enum names and the exported
symbols of the Linux shared libraries. I did no disassembly or decompilation,
and ran no code from the firmware. Each claim is marked as one of:

- **[E]** taken directly from a string or symbol (quoted where useful).
- **[I]** inferred from names, ordering or context. Treat these as hypotheses.

---

## 1. TL;DR

A still photo passes through three processors and about five firmware images:

```
 IMX710 sensor ──SLVS-EC──►  CP chip  (ARM32, TOPPERS/FMP RTOS, cpapp-b.bin)
                              DFE → CamCore ISP (Head→NR→Sig→Dev)
                              → DST → MBL → SRC → SPC → VFX → JPG ×5
                              + AE/AWB/AF/face/subject (EC/CC/LC/FC)
                              + SA DSP programs (sa_sabin_cp_*.bin)
                              ◄──OSPI/SPI──► ADAM AI unit (adam_app.bin + default.nab)
                                   │ PCIe (interchip DMA)
                                   ▼
                             MP chip  (CXD90057, AArch64)
                              av-cam.bin  "CAM_MP": import, LLC raw compress,
                                          resize, JPEG/HEIF encode (Imola2 codec)
                              Linux 4.9: appFw.so (UI/logic), libmpr.so
                                          (EXIF/header, SHA-256/sign, file write)
                                   ▼
                              ARW / JPG / HIF on card
```

---

## 2. Firmware layout relevant to imaging

The unpacked tree is `firmware.tar_unpacked/0700_part_image/dev/`.

| Partition / file | What it is | Evidence |
|---|---|---|
| `nflasha8/cpapp-b.bin` (18 MB) | **CP (camera processor) firmware.** ARM32 code (ARM reset vector) running TOPPERS-FMP RTOS. Runs the whole capture and ISP sequence. | [E] 883 source filenames; `TOPPERS-FMP/rtos/toppers_fmp`; `tomco.txt` RTOS config (`mpcp_exception_int_no`, `snapshotdbg_addr`…) |
| `nflasha8/loader_spi.bin`, `mini_ldr.bin`, `DGU.bin`, `MIS.bin`, `pcie_phy_fw.bin` | CP-side boot chain. DDR training and the PCIe link to the MP. | [E] `LDR:PCIe matched`, `pcie_stm_comm_ready`, `MIS for DGU6`, LPDDR training logs |
| `nflasha3/vmlinux.bin` | MP Linux kernel | [E] `Linux version 4.9.337-scel+ … Sony CE Linux 14.0.1.0 … Sat Oct 11 04:09:59 JST 2025` |
| `nflasha3/av-cam.bin` (13.8 MB) | **MP-side AV/camera media-processing image.** AArch64, with `0xffffffc0_01xxxxxx` VAs, `ORIL` header. Loaded by Linux (`fn=/system/av-cam.bin load=1`). | [E] `[CAM_MP]` (402 strings), `[SDF]`, `[IMLSTLENC]`, `[VDT]`, `[ADT]` |
| `nflasha3/adam_app.bin` + `nflasha15/data/ai_dict/default/default.nab` (39 MB) | **ADAM AI processing unit** firmware and its neural-net dictionary | [E] CP sources `adam_driver.cpp`, `adam_ospi_controller.cpp`, `adam_spi_controller.cpp`, `adam_gpio_controller.cpp`; WBI2 snapshot references `/system/adam_app.bin` next to `default.nab` |
| `nflasha15/lib/appFw.so` (100 MB) | Linux UI and business logic (`UIBiz_221H`): menus, settings, sequences such as `sequence_still_record.cpp` | [E] |
| `nflasha15/lib/libmpr.so` | Media recorder: still file creation, header, hash/sign, file write | [E] exported `mpr::RecordStill`, `mpr::stillrecord::_make_header`, `SigAndHashSa`, `ExecSkdSignOnCpu` … |
| `nflasha15/lib/libInfraAvbbc.so` | Linux↔RTOS command bridge for imaging jobs (JPEG/HEIF encode/decode, in-camera RAW develop) | [E] `ExecCmd_IMG_RawDevelop`, `ExecCmd_MC_EncodeHeif`, `ExecCmd_SDF_EncodeJpegMain` |
| `nflasha15/codec/vcd_firmware_imola2.bin` | "Imola2" video codec firmware. Also used for HEIF stills. | [E] `[IMLSTLENC]` HEVC intra 4x4…32x32 backup, HEIF `grid_info` |
| `nflasha15/sabin/*.bin` | Programs and tables for the "SA" DSP engines plus detection dictionaries | see §6 |
| `nflasha5` (WBI2, 267 MB) | Warm-boot (hibernation-style) snapshot of the running Linux system. fwtool does not parse it. | [E] magic `WBI2`; contains libmpr symbols and loader cmdlines |

**Two chips linked by PCIe.** [E] Several strings show this:
`FRONT_CP_INTERCHIP`, `InterChipImgInfoAccr.cpp`,
`[CAM_MP] … 4pixel Align error! CP:canvas.width[%d] MP:canvas.width[%d]`,
`[CAM_MP] … PCIeDma END`, `adt_flow_pcie_read.cpp`/`adt_flow_pcie_write.cpp`,
and the Linux kmods `pci_ep_cp.ko`, `pcie-if.ko`, `pcieatu.ko`. [I] This
matches the two-chip BIONZ XR design: a front "CP" for the sensor and ISP, and
a main "MP" SoC (CXD90057) for media, UI and the file system.

**Sensor.** [E] `Camera::Imager::IMX710::C_ImagerCtrl_IMX710`,
`ImagerDrvParam_IMX710`, `CetusSlvsecDriver`/`CetusSlvsecLink`. IMX710/IMX710E
is the only imager with a dedicated driver class. Other IMX part numbers
appear only once each, as leftovers from shared code. The sensor link is
SLVS-EC ("Cetus").

---

## 3. CP still-capture sequence (`cpapp-b.bin`)

The capture is driven by `CaptureManager` / `tsk_capcon_sequence.cpp`, a
"Stage" state machine. The source files are `Stage_*.cpp` and
`EC_CaptureRaw*.cpp`. The stage names below are [E] strings. The order is [I],
reconstructed from the stage names, their position in `.rodata` (the compiler
keeps per-file order) and the `Stg>` trace tags.

### 3.1 Initialization
- `Stage_CaptureInit` (`Stg>CapInit`, `Stg>InitAfter`): waits for
  `WAIT_IMG_PARAM`, runs `SetShutterMuteOn`, switches the DFS clock
  (`DFS_CAP_START_ERR CLK`), and allocates buffers (`GetMem:Raw`,
  `GetMem:DFERaw`, `GetMem:IDT`). It then acquires `CAM_HEAD`, `DFE` and
  `CLV` (camera live view).
- `Stage_WriteExifCaptureDateAndCreateSeedMaster`: records the EXIF date and
  creates a **random seed master** (`createSeedMaster SysCnt/SeedMaster`).
  [I] This seed feeds the per-block dither and noise-add generators: CamCore
  logs `DITH SEED is 0` / `NADD SEED is 0` for CAMHEAD, CAMDEV, CAMNRS, CAMLRC
  and CAMSIG.
- Lens and body handshake over **CAIF**, the camera↔lens/body-control
  interface: `Stg>CaCapStart`, `CaSend_CapSetting`, `CaRcvFocalLength`,
  `WaitLensVoltage`, `Emt_SetupCapture`, `WaitSetupCap`, `CaBeforeExp`.
  Messages include `CAP_REQ`, `PRE_EXP_SETTING`, `PREFIRE_*` (flash),
  `Pupil_Pos` and `EXP_READY`.

### 3.2 Flash pre-light (optional)
- `Stage_Prelight*`, `Stage_PrelightIDT_LuminousMultiFrame{,2nd,3rd}`,
  `Stage_PrelightIDT_NonLuminousMultiFrame`, `Stage_BranchForPrelightOPD`
  and `Stage_PrelightEnd`. Related AE files: `SB_CaptureRawPrelight*.cpp`,
  `EC_CapturePrelight.cpp`, `CC: CalcStrbWBContPreDet_*` (flash WB).
- Flicker scan: `Stage_OnePushFkScanDetWwait` / `…Calc` (anti-flicker
  shooting).

### 3.3 Exposure
- Shutter: `Stage_MkOpenWait` (mechanical), `EC_ElecShutter_Main.cpp`,
  `HybridShutter`, `EC_CurtainSpeedAdj.cpp`,
  `EC_NonlinearElecShutter_MechShutterTable.cpp`.
- `Stage_ExposureWait_1st` (`Stg>ExpWait1st(Main`, `SGC1 Kick(1st`). SGC1
  is the sensor sync/timing generator (`Camera::CamCore::Sgc1`).
- `ExposureTimerHandler`, `FpnrExposureTimerHandler` (long-exposure
  dark-frame NR) and `BulbExpReadTimerHandler`. Bulb exposures can be split
  (`Stage_BULB_SplitReadExecute`, `bulbFrameCount`).
- `Stage_NotifyLongExpNRCapturing` drives the "Long Exp. NR" progress UI
  (`NID_LONG_EXP_NR_PROGRESS` on the Linux side).

### 3.4 Sensor readout → DDR
- `Stage_ReadStart`, then `Stage_ReadExecute`
  (`Imager:SetRead` → `Imager:Read` → `Acquire:DFE` → `Acquire:DFE_TRANS`),
  then `Stage_DfeTrans`, which moves the raw frame through DFE into DDR.
- Raw buffers are managed by `RawMemManager*.cpp`. CamCore has a
  **compress/decompress engine** (`CompDecompController`,
  `RawcallbackCamCoreEnd_CompDecomp0/1`) and **RDC** raw-data-compression
  images (`RdcImage`, `RdcL0..L2`, `encType`, `lcut/rcut`). [I] The raw frame
  is held compressed in DDR between stages.
- **Blackout-free / async live view** while capturing: `Stage_*_AsyncLv`,
  `Stage_*BolAsyncLv`, `Stage_LvReadStart`, `JudgeNextAsyncLvStatusBOL` and
  `Stg>BOF_RdMgn_S(ALV|CLV|MAIN)`. [I] BOL/BOF are live-view frames
  interleaved with the main readout.

### 3.5 Detection on the captured frame
- `Stage_OPD` → `Stage_CalcCapParamAfterOPD`. OPD (optical detection)
  computes AE, AWB and histogram statistics from the **actual captured raw**
  through `FOPD` (`FopdAf`, `FopdVatr`, `FopdSdev`, `FopdRcraw`). Final
  development parameters are then recomputed from those statistics.
- `Stage_ADJ_DetectRAW`, `job_IQC_GetShiftPixel`,
  `job_IQC_ShortDarkLevelCalc` / `ShortOffsetLevelCalc`: black level and
  offset measured from optical black (`job_GetOpbDetectValueCpu`,
  `api_IQC_JudgeOpbArea`).
- `Stage_Orientation` (gravity sensor), `Stage_FaceDetect` (face boxes for
  EXIF and face-priority tone), `Stage_NotifyPersonalIdentification`.

### 3.6 Pre-review (instant review image)
- `Stage_PreReview*`, `Stage_Ezoom_Resize_PreReview` and
  `Prereview2ndPass_Base`. A quick YC image is made through SRC_LV and shown
  before full development ends (`NotifyDrawReview`).

### 3.7 Full development (`Stage_DevLater.cpp`)
- `Stage_DevLaterInit`: falls back to JPEG if needed
  (`Change StillRecMode to JPEG!!`).
- `Stage_PrepareDeconv`: allocates a **deconvolution PSF** table for `DCVP`
  (`Deconv PSF Table AllocNewWait`, `job_IQC_GetDcvpParam`, `cpt_PsfAddr`).
  The source table is `sabin/dcv_psf_table_still.bin`. [I] This is lens
  diffraction/blur compensation.
- `Stage_PrepareCDET`: chroma/colour detection pass (`KickCAM_CDET`,
  `cdetSplitStart`) that produces a PFR (pre-frame) image.
- `Stage_PrepareTanzaku*`: computes the **strip** split. *Tanzaku* (短冊) means
  vertical strips. The frame is cut into strips with overlap margins
  (`isp_nori`, which must be a multiple of 32) and processed in parallel on
  four ISP lanes (`ISP0..ISP3`; `IspParallel Isp%d Calc I2O/O2I`). The
  variants `Stage_PrepareTanzaku_CAMDEV_DST_SRCDEV_VFX[_SRCSCN]` name the
  block chain.
- The development chain is one of these stages. The exact chain appears as an
  [E] log string:
  ```
  CAMDEV_DST_MBL_SRC(MID)_SPC_VFX_SRC(SCN)
  ```
  - `Stage_Dev_Dst_Mbl_RecordRC_DithSpc_Vfx_SCN`: full quality, used for the
    main image.
  - `Stage_Dev_Dst_RecordRC_Vfx_SCN` and `Stage_Dev_Dst_NormRC_Vfx`:
    lighter variants.
  - `Stage_Dev_Vfx`: minimal variant.
  - Kick order logged: `SetPrmCAM_DEV` → `KickISP` → `KickSRC_SCN` →
    `KickVFX`. Completion callbacks: `IspCallbackEnd_{DST,MBL,SRC,SPC,VFX,SRC_SCN}_Base`.
- `Stage_Apollo`: multi-frame NR / composite (`ApolloNrBase`,
  `ApolloSA_Main`, `api_EC_GetApolloLapNum` meaning the number of frames
  overlapped). It uses motion estimation and references (`YC: [APL_ADDR]
  ME___OUT_ADDR`, `REF0/REF1_OUT_ADDR`, `MBL__OUT_ADDR`).
- `Stage_BFNR`: an SA-DSP noise-reduction function (`sa_func_BFNR_init`).

### 3.8 JPEG encode on the CP
- `Stage_Jpeg_Alloc_Mem` → `Stage_MainEnc` (`EncodeJpegBase MAIN`), then
  `Stage_ThmResize`/`Stage_ScnYcShareForThm` → `Stage_EncodeJpeg_SCN`
  (screennail) and `Stage_EncodeJpeg_THM` (thumbnail).
- Rate control: `GetQvalue`, `CheckStreamLength`,
  `DoubleEncode Flag Enable`, and on the MP side
  `encode retry … qvalue_idx`. [I] The encoder re-encodes with a different Q
  if the stream overflows its target size.
- Hardware: 5 JPEG engines (`PBL_AIC_PORT_G1_JPG0..4`), plus a QTABLE Y/C and
  a resizer in the JPEG block (`FW: JPEG RESIZE`).

---

## 4. ISP hardware model (CamCore / DFE / post blocks)

These are the register sub-blocks behind getter/setter classes in
`Camera::CamCore::*` and `Camera::DFECore::*`. The names are [E]. The
expansions are [I].

### 4.1 DFE: Digital Front End (sensor input)
| Group | Sub-blocks | Likely function |
|---|---|---|
| `Ifmt*` | Dec, Emb, Ps, Gif, TestGif | Input format: SLVS-EC decode, embedded-data lines, test pattern |
| `Corr*` | Clp, Dcm, Ddx, Dfi, Dl, Pga, Pg, Pls, Rpo, Tdl, Tzr, Mario{Dc,Pga,Pg,Rpo} | Clamp/black, defect handling, per-channel PGA gain, offsets |
| `Det*` | Buf, H3, Opbfk, Pg, Rpo | Detection: optical-black and flicker (`Opbfk`), histograms |
| `Cow*`, `Dwc`, `ImgDwc`, `ImgSdcDfiMro`, `ImgTopDclWbIwbOfst` | — | Compression/decimation, WB/offset at the front end |

### 4.2 CamCore: main Bayer→YC pipeline
Controllers: `CapController` → `NRController` → `EEController` →
`DevelopController`. Each has a `Split*` variant for tanzaku strips. There
are also `LVController` (live view), `CdetController`, `CompDecompController`
and `ZpdController`. The trace prefix `[CAM 0]`, `[CAM 1]`, `[CAM LV]` shows
**two still development instances (CAM0/CAM1) plus a live-view instance**.
[E] `FOPD … cam0(%d), cam1(%d), camlv(%d)`; AXI ports `G0/G1_CAM0_L0..L2`,
`CAM1_L0..L2`.

| CamCore unit | Sub-blocks | Likely function |
|---|---|---|
| `CamHead` | Pga, Olc, Shd, Snr, Fk, Kro, Lga, Mxc/Mxcm, Rpo, Sca, Ddx, Cmp, Pwg, Srsw, Fcp | Raw front: per-channel gain (`Drv.Head.r_pga/gr_pga/gb_pga/b_pga`), shading (lens vignetting), flicker, defect, scaling, compression |
| `CamNrs` | Nr, Wb, Ofst | Raw (Bayer) noise reduction |
| `CamNrv` | Dnr, Ofst | Further NR, modes `acm / dnr2 / dnr3` |
| `CamLrc` / `CamArc` | Rc, Wb, Ofst | Resize/correct stages (`ARCReductionRatio L/R/S`) |
| `CamCas`, `CamDcv` | Cas, Dcv | Deconvolution (`CamDcv`, fed by DCVP/PSF) |
| `CamSig` | **Itp**, **Apt**, Wb, Ofst | Demosaic (interpolation, `m_InterpMode`), aperture/sharpening, WB |
| `CamDev` | Ac, Awc, Edge, Gma, Kne, **Lmx**, Lut, Ofst, Pfr, Vatr, Yap, Yc, Ycp, Ydet | RGB→YC "develop": linear colour matrix, gamma, knee, LUT, edge enhancement, Y aperture, YC processing, Y detection |
| `CamTdl`, `CamRdc` | — | TDL, raw compression (RDC) |
| `Vatr`, `Sdev`, `Zpd` | — | AWB/AE statistics, sub-device stats, phase-detect AF pixel processing |

### 4.3 Post-CamCore blocks (×4 lanes: ISP0..3)
AXI port names give the block inventory [E]:
`G5..G8_{MBL,SPC,SRC0,SRCE0,SRCE1,VFX4B}_ISP{0..3}`, `G3_DST0..3`,
`G4_DSTLV0/1`, `G1_JPG0..4`, `G11_DCVP`, `G9_{FOPD,IDT,PRC,APLS,SRCD_DSP}`,
`G1/G11_SA1_*`.

| Block | Evidence | Likely function |
|---|---|---|
| **DST** 0–3 (+DSTLV) | regs `DIST_H`, `DIST_V`, `CORE_V`, `RBC`, `DST DIST HVECTORS`; `distortion_corrector.cpp` | Lens distortion correction. [I] `RBC` handles lateral chromatic aberration (R/B channels). |
| **MBL** | `FW: MBL CCNR / YKNR / KKNR / DITHER / CP / COMMON` | Multi-band NR: chroma NR (CCNR), luma NR (YKNR), a further NR band (KKNR), output dither |
| **SRC** (SRCDEV, SRCMID, SRCSCN) | `SRCDEV TOP/CORE_HV`, `SRCSCN …`, `ModuleRcResize`, `ApiResizeRotate` | Scaler/resize: main → intermediate → screennail |
| **SPC** | `SPC_PRM_MOD`, `SPC_SMC_PRM_MOD`, `DithSpc`; tables `spica_cetus_still_{y,c}_tap_step{1,2}.bin` | [I] Spatial filter / detail processing with separate Y and C tap tables in two steps |
| **VFX4B** | `VFX REG/REG_G`, effects, `FillByVfx` | Format conversion, picture effects, fill/borders |
| **JPG** 0–4 | `JPEG IN/OUT/QTABLE Y/C/RESIZE` | Baseline JPEG encoders |
| **DCVP** | `api_DCVP_Start`, PSF tables | Deconvolution pre-processor |

---

## 5. Image-quality parameter computation (CP software)

The parameters are computed per frame by the `EC_*` (exposure control),
`CC:` (colour control), `PQD_*` (picture-quality determination) and `YC:` /
`job_IQC_*` modules. The `[I]` and `[O]` strings in this section are the
firmware's own trace labels for inputs and outputs, not this document's
evidence tags. The trace lists contain about 3,300 such labels.

- **PQD modules** [E]: `PQD_Black`, `PQD_Baseband`, `PQD_DigitalGain`,
  `PQD_Gamma` / `PQD_GammaTable`, `PQD_Knee`, `PQD_ToneCurve_*`,
  `PQD_SignalLevel`, `PQD_Flicker*`, `PQD_Histogram_YDET*`.
- **Inputs (`[I]`)**: `scene`, `contrast`, `shadow`, `highlight`, `Fade`,
  `colorMode`, `pictureEffect`, `isPictureProfile`,
  `pictureProfileGammaType`, `cinematoneMode`, `procolorMode`, `baseLook`
  (Creative Look), `isHeifHLG`, `linearGammaOn`, `isoTable`, `isDualRec`,
  `iAutoGammaScene`, `DroLevel`.
- **Outputs (`[O]`)**:
  - WB gains: `WBGainR/G/B`, `WBGainStd`.
  - 3×3 colour matrix: `ss_RGBMatrixRR…BB`.
  - Gamma: a **129-point master gamma** (`<Gamma> mgam_tbl[0..128]`) plus 12
    segment-slope selectors `is_s0..is_s11`.
  - Knee: `KneePoint`, `KneeSlope`, `kneegain`.
  - DRO: `DroLevelGain`, `SyncDroControlFlags`.
  - Picture Profile black gamma: `PPBlackGammaPoint[0..27]`.
  - `isSlog3OOTFTbl`.
  - YC clip, black levels and `is_rgb_neg_en`.
  - Saturation: `YSat[0..4]`, `SatH/L`.
  - Front-end gains: `Drv.Head.*_pga`, `Drv.corr.*_pga`.
- **Lens data from the mount protocol** [E]: `Mount_DividedInfo_*` for
  `CamCurveData`, `EclipseData` ([I] vignetting/shading),
  `BreathingCorrectionData`, `FnoCorrectAbility` and `SteadyShotInfo`.
  Related: `job_Mount_YC_SetAberrationDataInfo`,
  `job_EC_SetLensCorrectParam`.
- **Parameter synchronization** for the strip engines:
  `ImageParam_Capture[_Share|_WriteBack]`, `SyncDcvManager`,
  `SyncSpcManager`, `SyncAICSetter`, `SyncTanzCalc`, `SyncRCCalc`.

---

## 6. SA DSP programs and detection (`sabin/`)

The `sa_sabin_*.bin` files are "SP"-format containers of named DSP functions.
The names below are [E] strings in each container:

| File | Functions |
|---|---|
| `sa_sabin_cp_cam_post.bin` (CP) | `FDN`, `PDN` (face/person detect), `AED`, `AED2`, `BED` (animal/bird eye), `SCD`, `UDRT`, `SMOD`, `HIST`, `DET`, `DEFDET` (defect detect), `DTCF`, `DNB`, `FRC2`, `ZPHD2`, `ZUP`, `FILL`, `ROT90` |
| `sa_sabin_cp_zima_post.bin`, `sa_zoom_nr.bin` | `ZNR` (zoom NR) |
| `sa_sabin_mp_cam_post.bin` (MP) | `SHA256`, `NV12CONV`, `PCMCC`, `FILL`, `ROT90` |
| `sa_sabin_mp_zima_post.bin` (MP) | Audio: `AACENC/AACDEC`, `LPCME/LPCMD`, `A3E` |

The other files are dictionaries and tables: detector dictionaries
(`fdn_*_dict`, `pdn_dic`, `aed*_dic*`, `bed_dic*`, `scd_dic*`, `udrt_dic*`),
`dcv_psf_table_{still,movie_*}` (header `imager_test` / `lens_test_5` /
`20190411_…`), `star_kernel_param.bin` (purpose unknown) and the SPC tap
tables.

Subject detection and tracking runs on the CP (`Camera::FC::*`,
`Camera::Minna::{Fdn,Pdn,Drt,Scd,Staple,Keypoint::Aed/Aed2/Bed}`), with
**ADAM** for the AI subject recognition (`adam_recognition_param_generator`,
`auto_recog_*`). Face results feed tone (`FaceYnAveLog…`, `SB_Face.cpp`),
EXIF/MakerNote (`fc_alg_exif_face_data.cpp`) and AF.

---

## 7. MP side: media processing and file creation

### 7.1 `av-cam.bin`: `CAM_MP` still sections [E]
```
Section_Entry
 → Section_ImportAndSrw   (PCIeDma import from CP; srw_post_mode 0:YC420 1:YC422 2:BAYER)
 → Section_Llc            (lossless RAW compression, AcquireLLC / llc_encode_rectangle)
 → Section_ConfluenceRaw / Section_Confluence   (join RAW + YC streams)
 → Section_ResizeYc       (Resize / ResizeMulti / ResizeWithKwk)
 → Section_Encode         (MAIN / SCN / THM / EMB JPEG; HEIF via Imola)
 → Section_DecodeJpg      (decode path, e.g. for review/convert)
 → Section_Exit
```
Logged enums [E]:
- `stl_file_format`: 0 NONE, 1 JPEG, 2 RAW, 4 HEIF (a bitmask, so RAW+JPEG
  and RAW+HEIF are possible).
- `uc_StillRawFormat`: 0 COMP, 1 UNCOMP, 2 LLC (lossless compressed).
- `uc_StillQuality`: 0 STD, 1 FINE, 2 EXFINE, 4 LIGHT.
- `uc_StillSize`: 0 L, 1 M, 2 S, 3 VGA.
- `stl_aspect`: 16:9, 4:3, 3:2, 1:1, 17:9.
- `colorMode`: sRGB, Adobe, HLG.
- `hif_chroma_format`: 4:2:0 or 4:2:2.
- `hif_gamma`: STD or HLG.

**HEIF** [E]: encoded by the Imola2 codec (`[IMLSTLENC]`) as a **grid of
HEVC-intra tiles** (`grid_info: num_of_grid x.y`, `black_belt` padding). The
Main, Scn and Thm images each have their own HEIF target size.

### 7.2 Linux userland
- `appFw.so` holds the user-facing settings that become capture parameters:
  `BKID_APP_SETTING_STILL_HEIF_QUALITY`, `…_RAW_COMPRESS_MODE`,
  `…_HIGH_ISO_NR`, `…_LONG_EXPOSURE_NR`, `sequence_set_still_format.cpp`,
  `sequence_start_pixel_shift_multi_shoot.cpp`, and others.
- `libInfraAvbbc.so` sends RTOS jobs: `ExecCmd_SDF_EncodeJpegMain`
  (main/scn/thm), `ExecCmd_MC_EncodeHeif` (converts capture gamma,
  colorimetry, colourspace and bit depth), `ExecCmd_IMG_RawDevelop` (in-camera
  RAW development) and `ExecCmd_SDF_RawResizeRotate`.
- `libmpr.so` writes the file:
  - `mpr::RecordStill` → `stillrecord::_record_still`.
  - `_make_add_if_t(…JpgInfo, RawInfo, HifInfo…)`.
  - `_make_header` / `FinalizeStillHeader` build the EXIF/ARW header and
    MakerNote. The CP fills MakerNote source data through
    `CS_ExifMakerNote.cpp`, `EC_MakerNote.cpp`, `PublicMakerNoteSrcData` and
    `PrivateMakerNoteSrcData`.
  - `SigAndHashSa` / `ExecHashOnCpu` / `ExecSkdSignOnCpu` /
    `ExecEncryptOnCpu`: a SHA-256 hash, computed on the SA DSP or the CPU, and
    a signature over the image. [I] This is the in-camera authenticity /
    signing infrastructure. Whether it is enabled on the a7C II is unknown.
  - `fsys_callbackfunc` → `_write_finished`, then the `sidb` DB update.

---

## 8. Condensed pipeline (one RAW+JPEG/HEIF shot)

1. **UI/Linux** (`appFw.so`): release, then capture parameters (format,
   quality, NR, look) are sent to the CP.
2. **CP init**: buffers and resources, seed master, lens CAIF handshake,
   optional pre-flash and flicker scan.
3. **Exposure**: mechanical, electronic or hybrid shutter, timed through
   SGC1.
4. **Readout**: IMX710 → SLVS-EC → DFE (format, clamp, PGA, defect,
   OB/flicker detection) → compressed raw in DDR. Async live view keeps the
   EVF running.
5. **OPD on the captured raw**: final AE/AWB/tone parameters (PQD/EC/CC),
   face and orientation.
6. **Pre-review**: fast YC preview for the EVF.
7. **Development**, split into 4 tanzaku strips across ISP0..3:
   CamHead (gain, shading) → NRS/NRV (raw NR) → [DCVP deconvolution] →
   SIG (demosaic, sharpening, WB) → DEV (matrix, gamma, knee, LUT, edge, YC) →
   DST (distortion, lateral CA) → MBL (chroma/luma NR, dither) →
   SRC (resize) → SPC (detail filter) → VFX (format/effects) → SRC_SCN
   (screennail). Multi-frame modes add Apollo NR or composite.
8. **CP JPEG** (main, screennail, thumbnail) with Q-retry. The raw goes
   through RDC.
9. **PCIe → MP `CAM_MP`**: import, LLC/COMP raw packing, resize, HEIF tile
   encode on Imola2 (or JPEG), confluence of the streams.
10. **libmpr**: EXIF, MakerNote and ARW header, optional hash/sign, then the
    card write and DB update.

---

## 9. Open questions / next steps

- Confirm the strip count and overlap: find the code that consumes
  `isp_nori` and `DevIPParallel_LR_Base_New`. [I] "LR" suggests an extra
  left/right split across CAM0/CAM1 on top of the four ISP lanes.
- Expand the abbreviations (Olc, Kro, Lga, Mxc, Pwg, Srsw, Yap, Vatr, Cas,
  Lrc, Arc). This needs disassembly of the getters/setters in `cpapp-b.bin`.
  Load it as ARM32 little-endian, find the base address from the reset vector
  at offset 0, and use the RTTI vtables as anchors.
- Parse `nflasha5` (WBI2). It is a live-system snapshot and may contain
  decompressed tables or runtime state that the static images lack.
- Decode the format of `dcv_psf_table_still.bin` (PSF kernels per
  lens/aperture?) and of `star_kernel_param.bin`.
- Check whether the `SigAndHash` / SKD signing path can be reached on this
  model.

---

## Reproduction

```sh
python3 -m venv $S/venv && $S/venv/bin/pip install pycryptodomex pyyaml
$S/venv/bin/python fwtool.py unpack -f BODYDATA-a7c2-2.1.DAT -o $S/unpacked   # ~25 s, ~3.9 GB
D=$S/unpacked/firmware.tar_unpacked/0700_part_image/dev
strings -t x -n 6 $D/nflasha8_unpacked/cpapp-b.bin > cpapp.strx            # CP
strings -n 6 $D/nflasha3_unpacked/av-cam.bin        > avcam.str             # MP media
grep -E '^N[0-9]+' cpapp.strx | sed 's/^[0-9a-f]* /_ZTS/' | c++filt         # RTTI
llvm-nm -D --defined-only -C $D/nflasha15_unpacked/lib/libmpr.so            # file writer
```
Useful anchors in `cpapp-b.bin` (file offsets):
- `0x37e748`–`0x394e08`: the `Stage_*` function-name strings, in source order.
- `0x39b354`–`0x39dd68`: per-block register dump labels (DST, MBL, SPC, VFX,
  SRC, JPEG).
- `0xe88fc4`–: PQD `[I]` / `[O]` parameter traces.

---

## 10. Colour pipeline (follow-up)

Evidence tags are as in the rest of this file: **[E]** comes straight from a
string, **[I]** is my inference.

```
Bayer raw
 → black/OB clamp, per-channel PGA gain              (DFE Corr*, CamHead Pga)       [E]
 → WB gains R/G/B                                    (CamNrs/CamSig/Vatr Wb; WBGainR/G/B) [E]
 → demosaic                                          (CamSig Itp, m_InterpMode)      [E]/[I]
 → multi-axis linear matrix                          (CC "Lmat", us_lm_axis[n],
                                                      coef_mix_gain; CamDev Lmx)     [E]/[I]
 → gamma 129-pt + knee + DRO + black gamma           (mgam_tbl[0..128], Kne,
                                                      DroLevelGain, PPBlackGammaPoint) [E]
 → 2D/3D LUT (look)                                  (CC Create3DLUT Level/ConvSD,
                                                      Copy2DLUT, DevLutSetter,
                                                      "CamCore 3D-Lut table Write")  [E]
 → RGB→YC, saturation (YSat[0..4]), colour depth/phase (PP), Y gain/offset, clips  [E]
 → output colour space sRGB / AdobeRGB / HLG (HEIF), BT.2020 flags                 [E]
```

- **Multi-axis matrix.** [I] The colour matrix is split into hue segments:
  the `us_lm_axis[n]` boundaries are hue axes, each segment has its own
  coefficients, and `coef_mix_gain` blends neighbouring segments. This is the
  "multi-matrix" approach used on Sony broadcast cameras.
- **Look (2D/3D LUT).** [I] The look is applied through a 2D/3D LUT inside
  CamCore. `Create3DLUT … Level` probably means a look rendered at a given
  strength, such as Creative Look intensity.
- **Movie/display LUT block.** [E] A separate `MLUT` block has EI gain, three
  1D LUTs, a 3D LUT, matrices A–D, rgb↔yc conversion and ASC-CDL. It loads
  `SL3SG3*.cube` LUTs (S-Log3/S-Gamut3 → Rec.709). [I] It serves movie, log
  and display assist.
- **AWB inputs.** [E] They include:
  - ADAM AI scene classes: sky, snow, green, evening, meal, sea.
  - Skin-aware OPD tables (`opd_cycle_table_skin`).
  - An IR sensor value (`upm_set_ir_sensor_value`).
  - Flash ratio estimation (`CalcStrbWBContPreDet`).
  - AWB aim/direction/effect/contrast terms (`AimR/B`, `DirR/B`, `EfctR/B`,
    `ContR/B`).
- **RAW metadata.** [E] The RAW file carries a camera colour matrix:
  `FW: RawColorMatrix[%d] …`, `SetRawTagParam()`.

---

## 11. Creative Look storage (follow-up)

The evidence tags below are as in the rest of this file.

- [E] Look enum (`VAL_setting_creative_style_plus_*` in appFw.so):
  - STANDARD (ST), PORTRAIT (PT), NEUTRAL (NT), VIVID (VV), BRILLIANT (VV2)
  - FILM (FL), FILM2 (FL2), FILM3 (FL3), AIRY (IN), RETRO (SH)
  - BLACK_WHITE (BW), SEPIA (SE)
  - CREATIVE_BOX_1..6 (the 18 `BKID_APP_CREATIVE_LOOK_OPTION_*0..17` slots)
- [E] Per-look user options: Contrast, Highlight, Shadow, Fade, Saturation,
  Sharpness, Sharpness Range, Clarity, Fineness.
- [E] Inside the CP firmware the look reaches PQD/CC as `baseLook`. It selects
  gamma tables (`GetGammaTableNo…`), matrix and LUT data (`Create3DLUT …
  Level`).
- [I] No look is stored as a named or portable LUT file. A scan of
  `cpapp-b.bin` finds about 800 unlabeled monotonic 129-entry u16 tables,
  starting around `0xdbcfa6`, which are candidates for gamma/tone tables.
  Assigning any of them to FL would mean disassembling the `baseLook` →
  table-index code.
- `0110_backup/SYSIPSX-DSLR/PP/CX8970x_*.bin` ("BK4", 2.39 MB per region) is
  the settings-backup default store. Its structure is an index of 6-byte
  entries followed by a data area. It does not obviously hold the look
  tables.
- [E] appFw.so also contains the menu labels `FL2(Film 2)` and `FL3(Film 3)`
  and the per-slot values `VAL_creative_look_option_lookN_LOOK_FILM2/3`. The
  a7C II officially offers 10 looks, so these entries are hidden in the UI.
  [I] It is unverified whether CP image tables for FL2/FL3 are present.
- Signing (§7.2): firmware 2.00 for the a7C II added digital signatures for
  still images (per press coverage). That fits the `SigAndHash`/SKD path in
  libmpr.
- Repacking: `fwtool/sony/fdat.py` `AesCbcCrypter.encrypt` raises
  `Encryption not supported`, so a modified CXD90057 image cannot currently
  be rebuilt. The 256-byte trailer is not checked by fwtool. [I] It is likely
  a signature that the camera verifies.

---

## 12. Loading `cpapp-b.bin` for disassembly / emulation (follow-up)

The evidence tags below are as in the rest of this file.

- **Load base `0x00108000`.** [E] The reset stub at offset 0 does
  `ldr r1,=0x0010800c; add r1,#4; bx`, jumping to offset `0x10` (SVC-mode
  setup). Checking against strings confirms the base:
  - Thumb-2 MOVW/MOVT constants that point to the start of a string: 1,271
    for base 0x108000, against ≤45 for every other candidate base tried.
  - Literal-pool pointers to the start of a string: 1,235 for base 0x108000.
- **Code is mostly Thumb-2.** The capstone disassembly is clean.
- **Colour-control anchors (VA):**
  - `0x23dd84`: the call that prints `CC: Create3DLUT … Level:%d ConvSD:%d`.
    [I] The LUT is built in software by a loop over a 9-step grid. It reads a
    constant table at `0xf5f2f8` (stride 27 = 9×3) and per-look
    coefficients from the CC context (`+0x6b0`, entry size `0x654`).
  - `0x240852`: `CalColorParamSlctStl()`, which selects the still colour
    parameters by scene, colour mode and look.
- **Feasibility.** [I] The colour/tone parameter maths (matrix, gamma, knee,
  3D LUT) is plain firmware code, so it could be decompiled or emulated
  (Unicorn) to dump each look's tables. The pixel processing itself (demosaic,
  NR, sharpening, MBL/SPC) runs in undocumented silicon and can only be
  approximated.

## 13. Black-box simulator: RAW in -> camera JPEG out (`sonysim.py`, 2026-10-11)

The colour/tone pipeline is modelled as an unknown per-pixel function. No firmware code is used.

- **Training pairs need only the ARW.** The a7C II ARW embeds a full-size 7008x4672 JpgFromRaw with the camera's own
  rendering (same look, WB and DRO). On the FL chart shots it matches the HEIF to 0.46 / 0.60 mean dE2000.
- **Input.** RAW -> scene-linear Rec.2020 (D65, as-shot WB, 1.0 = raw white), using dcraw-style matrix normalisation.
  LUT domain is per-channel log2, -14..+2 EV.
- **Registration.** The camera JPEG is lens-corrected, so it is mapped onto the RAW with a scale + k1/k2 radial + shift
  model fitted from tile phase correlation. Residual is 0.05 px (28 mm) and 0.11 px (20 mm) at quarter scale.
- **Fit.** One 33^3 LUT, log2 RGB -> sRGB-encoded output. Flat, unclipped pixels only, binned at 64^3; trilinear least
  squares with a 3D second-difference (Laplacian) prior.
- **Results** on photo-v22b DSC06539 (Daylight) / DSC06541 (Custom WB), FL, DRO Auto, Clarity +2. Mean / p95 dE2000:

  | | DSC06539 | DSC06541 |
  |---|---|---|
  | plain sRGB, exposure matched | 8.8 | 12.4 |
  | fit on both (in-sample, smooth 0.3) | 0.45 / 1.14 | 0.58 / 1.45 |
  | fit on the *other* image only (smooth 1, now default) | 2.10 / 5.9 | 1.76 / 5.5 |
  | same model, scored against the HEIF | 0.46 / 1.01 | 0.60 / 1.48 |

  For comparison (§40b of gr3-firmware): the Adobe A7 IV FL DCP on the same ARWs scores 2.82 / 5.67 (patch means vs HIF).
  The cross-image error is coverage: each monitor chart covers about 1-1.5k of the 33^3 cells. DRO Auto (local) is also
  baked in.
- **Limits.** Local operators (DRO, Clarity, sharpening, NR) are not modelled. Colours outside the trained gamut
  extrapolate affinely. A GR III DNG goes through the same input path (its own DNG ColorMatrix) and needs about
  -0.65 EV (exposure link of §40b). On the GR, saturated blues show noise, because the LUT is steep there.
- **To improve.** Shoot more FL RAW (DRO Off, Clarity 0 if the look is wanted without it): real scenes with foliage,
  sky, skin, saturated objects and highlights. Then run `pairs` on each ARW and `fit` on all of them.
- **Grey-axis prior, 2026-10-12.** `fit --neutral W` adds equal-RGB samples (grey output, lightness taken from a first
  fit). The monitor grey is never neutral in either training shot (R/G 0.84-0.86), so the true neutral axis was being
  extrapolated: chroma up to 3.2 across -6..+2 EV. With W = 10 it is <= 0.1, and in-sample error goes 0.47 -> 0.49.
  `fl_a7c2.npz` / `FL_a7c2.cube` are now this fit.
- **GR III firmware.** This model is now the Sony FL of the GR III films build v33b
  (`../FINDINGS.md` §53).
