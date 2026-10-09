# GR III 固件 2.10 图像管线逆向工具

[English](README.md) | **简体中文**

为理光 GR III 固件 2.10 制作的自定义胶片风格（Kodak Ektar 100、Gold 200、Portra 400、Fujifilm Pro 400H、
Kodak Vision3 250D）以及 RAW 降噪修改，全部通过离线修补官方升级文件实现。研究笔记见 `FINDINGS.md`（英文）。

**不包含：** 任何理光固件、修补后的固件镜像或照片。你需要自备 `fwdc239b.bin`（2.10 版），以及
`gr4_editor` 固件容器编解码器（默认路径 `../gr-custom-tool`）。

> [!WARNING]
> **免责声明 —— 一切风险由使用者自行承担。** 本项目是非官方的逆向工程研究。刷入修改过的固件存在风险：
> 可能导致相机永久变砖、硬件损坏、照片或设置损坏，并且几乎必然使保修及厂商支持失效。这些补丁仅经过离线
> 仿真验证，并只在一台相机上测试过；无法保证它们在你的相机上可用或安全。对于因使用本仓库任何内容而造成的
> 任何损坏、数据丢失、相机变砖或损坏，以及任何其他后果，作者**不承担任何责任**。如果你不能接受失去这台相机，
> 请不要刷机。
> 本项目与理光映像（Ricoh Imaging）无任何关联，未获其认可或支持；文中产品名称均为其各自所有者的商标。
> 软件按"原样"提供，不附带任何形式的担保（见 `LICENSE`）。
>
> 如中英文版本有出入，以英文版 `README.md` 为准。

胶片目标效果由 [spektrafilm](https://github.com/andreavolpato/spektrafilm) 的 LUT 渲染（CC BY-SA 4.0 +
spektrafilm LUT 许可）：`work/**/fits` 中拟合出的曲线和矩阵源自这些 LUT；使用时请注明 spektrafilm 并以相同方式共享。

许可：代码和笔记采用 MIT 许可（`LICENSE`）；`work/**/fits` 中的拟合数据源自 spektrafilm LUT，仍遵循其
CC BY-SA 4.0 + LUT 许可条款。

仅限离线使用。输入文件：`../fwdc239b.bin`（SHA-256 `d6a3c9c2…54bfd4`）。所有地址仅对该文件有效。

环境准备（Python 3.12，需要本地有 gr-custom-tool 的编解码器）：

```sh
python3 -m venv .venv && .venv/bin/pip install capstone numpy unicorn==2.1.4
mkdir -p work/fw
.venv/bin/python -I -c "
import sys; sys.path.insert(0,'../gr-custom-tool')
from gr4_editor.codec.container import inspect_container
from gr4_editor.codec.frames import decode_payload
d=open('../fwdc239b.bin','rb').read(); i=inspect_container(d)
dec,_=decode_payload(d[128:i['payload_end']], i['decoded_size'])
open('work/fw/rtos.bin','wb').write(dec[0x10870:0x10c5e30])"
```

| 文件 | 用途 |
| --- | --- |
| `fw.py` | RTOS 地址辅助工具、交叉引用（MOVW/MOVT、BL、字面量）、反汇编 |
| `emu.py` | Unicorn 仿真框架（内存分配 / assert / 日志 / SVC 桩函数） |
| `run_tuning.py` | 针对指定内部色调槽位运行 `ImageTuningStill::Make`，返回 R2Y 参数块 |
| `diffmodes.py`、`sens.py` | 比较各模式 / 各图像参数下的 R2Y 输出差异 |
| `cube_fit.py` | 把 .cube LUT 拟合为风格矩阵 + 交叉冲洗曲线（需在装有 colour-science/scipy 的 venv 中运行，例如 spektrafilm 的环境） |
| `make_film.py` | 把 cube_fit 结果写入交叉冲洗模式（独立记录 + 矩阵 + 9 条曲线） |
| `verify_film.py` | 对 make_film 输出做离线检查，并与原厂固件比较仿真的 R2Y 差异 |
| `make_films.py` | 用四种胶片模式替换交叉冲洗 / 鲜艳 / 复古 / HDR 色调（记录、曲线、选择器代码补丁）+ 图标 + 名称（FINDINGS §14） |
| `make_icons.py`、`make_names.py` | 重绘 ICONBIN 中的模式图标 / 在全部 21 种界面语言中重命名模式（供 make_films 调用） |
| `verify_films.py` | 对 make_films 输出做离线检查（仿真静态拍摄 + 实时取景、名称、图标） |
| `make_ma_probe.py`、`make_ma_probe2.py`、`verify_ma_probe*.py`、`make_hue_chart.py` | MultiAxial 探测固件（FINDINGS §15、§16）及其色卡 |
| `raw_nr.py` | RAW（PPU Bayer）降噪补丁：关闭（`make_films.py --raw-nr-off`，§21）、仅在 ISO ≥ 6400 时开启（`--raw-nr-from-6400`，§21b）/ 仅在指定 ISO 以上开启（`--raw-nr-above 8000`，§21c） |
| `raw_noise.py` | 测量 DNG 中的噪声相关性，以检测 RAW 降噪（FINDINGS §21） |
| `cca1.py`、`cca1_fit.py`、`verify_cca1.py` | 各胶片的 3x3 CCA1 暖色修正：拟合、补丁（`make_films.py --cca1`）、仿真检查（FINDINGS §22g；v10 起由 film_cave.py 取代） |
| `joint_fit.py` | 联合重拟合风格矩阵 + 胶片曲线 + 后置 3x3 矩阵（胶片 v9，FINDINGS §22i） |
| `make_films10.py`、`film_cave.py`、`armasm.py`、`verify_films10.py` | 胶片 v10：五种胶片（漂白效果 -> Vision3 250D，曲线以节点形式存储），通过 RGB->YCbCr 矩阵实现伽马后 3x3 矩阵，仿真检查（FINDINGS §22l；需要 Homebrew llvm 提供的 llvm-mc） |
| `lab_fit.py` | 以感知色差（dE2000）重新拟合：风格矩阵 + 后置矩阵 + 曲线修正（胶片 v11，FINDINGS §22m） |
| `make_cca1_probe.py` | 临时固件：v7 + CCA1 红蓝互换（证明 CCA1 处于生效状态） |
| `eval_warm.py` | 胶片拟合在暖色（黄/橙）与整体上的误差（胶片 v3，FINDINGS §19） |
| `gr3patch.py` | 概念验证构建器：修补风格矩阵并重新打包容器（复用原厂数据帧） |

已在一台 GR III（固件 2.10）上实机测试：胶片 v2–v10 及 RAW 降噪版本（FINDINGS §14–§22m）。胶片 v11 尚未实机测试。
