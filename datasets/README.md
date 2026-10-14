# 科研数据集

每个数据集文件夹都是一个自包含的科学数据单元，包含四样东西：

| 文件 | 作用 |
| --- | --- |
| `sample_*` | 原始数据（厂商容器或开放格式） |
| `*.metadata.json` | 样品、仪器、单位、点数、已知峰位等描述 |
| `*.parser.json` | 该用哪个解析器、哪种字节序 / 单位约定 |
| `example_workflow.json` | 消费该数据的工作流示例 |

```bash
# 运行全部数据集示例工作流
python scripts/run_dataset_examples.py

# 只校验不执行
python scripts/run_dataset_examples.py --validate
```

## 目录结构

```
datasets/
├── demo/                    通用示例数据（三个官方 Demo 工作流直接引用）
│   ├── caffeine_ms.xy               咖啡因 EI-MS 谱（401 点，XY）
│   ├── molecule_library.csv         10 个分子的性质库
│   ├── battery_candidates.csv       10 种电池正极候选材料
│   └── example_workflow.json        未知化合物鉴定链
├── nmr/                     核磁原始数据
│   └── bruker_nmr/sample_01.d/   TopSpin 实验文件夹（acqus + pdata/1/1r）
├── xrd/                     粉末衍射
│   └── lifepo4_pxrd/        LiFePO4 Pnma 参考谱（2201 点，Cu Kα）
├── spectroscopy/            分子光谱
│   ├── polystyrene_ir/       JCAMP-DX 5.01 聚苯乙烯红外谱（1501 点）
│   └── shimadzu_spc/         Galactic SPC 容器（1800 点 FT-IR 透过率谱）
└── microscopy/              显微成像
    └── lifepo4_sem/         SEM 显微照片（640×480 PNG，12 nm/px）
```

## 厂商容器如何进入平台

规格要求的链路是
`Instrument → Parser → Vendor Adapter → Scientific Object → Feature Extraction`：

```
datasets/nmr/bruker_nmr/sample_01.d/
    │
    ├─ acqus ────────────► 文本参数（SW / O1 / SFO1 / NUC1 / NS / TE）
    ├─ pdata/1/procs ────► 处理参数（SI / SF / OFFSET）
    └─ pdata/1/1r ───────► 二进制 int32 谱（自动探测字节序）
              │
              ▼
      BrukerAdapter.read()
              │  ppm 轴 = O1 ± SW/2
              ▼
      Spectrum（32768 点，6 个 1H 峰）
              │
              ▼
      extract_features() → metadata["extras"]["features"]
```

在节点里使用：

```json
{
  "id": "load",
  "type": "VendorSpectrumNode",
  "params": { "path": "datasets/nmr/bruker_nmr/sample_01.d" }
}
```

## 支持的厂商容器

| 厂商 | 扩展名 | 真实解码内容 | 其余处理 |
| --- | --- | --- | --- |
| Bruker | `.d` 文件夹、`.1r`、`.1rr` | `acqus` / `procs` 文本参数、`1r` int32 谱、ppm 轴 | `fid` / `ser` 报元数据后回退通用解析器 |
| Shimadzu | `.spc` | Galactic SPC 主头 + float32 谱、单位码、透过率自动反转 | `.qgd` / `.lcd` 只读签名与长度 |
| Thermo Fisher | `.raw` 文件夹、`.rawlf` | `Method.txml` / `ExternalCalibration.xml` 元数据 | OLE2 二进制需 `msconvert` 导出 |
| Waters | `.raw` 文件夹、`.arw` | `_HEADER.TXT` / `_INLET.INF` / `_FUNC*.DAT` 列表 | 需 `msconvert` 导出 |
| Agilent | `.d` 文件夹、`.yep` | `*.M` 方法文件 / `AcqData/MSTable` | 需 ProteoWizard / MassHunter 导出 |

无法完整解码时，适配器**不报错**：它返回能读到的元数据，并在
`metadata["fallback"]` 里写明原因，`metadata["engine"]` 记录实际解码者，
因此「真实仪器数据」与「内置模拟器数据」在 provenance 上始终可区分。

## 数据许可

`datasets/` 下所有文件均由平台生成（CC0），可自由用于测试与演示。
替换为自有数据时，请同步更新同目录的 `*.metadata.json` 与 `*.parser.json`。
