# 节点能力与状态目录（v0.7.3）

> 本文件由 `scripts/node_catalog.py` 自动生成，请勿手工编辑。
> 数据来源：`node_registry/registry.json`（节点注册表扫描结果）。

- 节点总数：**101**
- 分类数：**30**
- 扫描模块：**56**
- 尚无验证证据的节点：**96**（未验证 ≠ 不可用，但**不得**宣传为已验证）

## 能力标签说明

| 能力标签 | 含义 |
| --- | --- |
| `requires_network` | 会访问网络 / 云端服务（不可达时诚实回退内置库） |
| `requires_gpu` | 需要 GPU；不可用时明确回退 CPU 或报告不可用 |
| `requires_external_software` | 调用外部科学软件（缺失时回退内部近似引擎并标注） |
| `writes_files` | 会生成或覆盖产物文件 |
| `experimental` | 实验性能力，结果需人工复核 |
| `sensitive_data` | 可能处理敏感数据，建议使用本地模型 |
| `nondeterministic` | 非确定性节点，不承诺逐位可复现 |

## 执行来源：capability_status（可以主张什么）

| 状态 | 含义 |
| --- | --- |
| `verified` | **有独立已知答案验证证据**（`validation_evidence` 非空）；无证据的 `verified` 声明会被自动降级为 `executable` |
| `executable` | 当前环境可运行，但未经过独立验证 |
| `experimental` | 可运行，但科学结论未经确认 |
| `unavailable` | 声明的依赖在当前环境缺失（**绝不伪装成功**） |

## 执行来源：execution_mode（实际由谁计算）

| 模式 | 含义 |
| --- | --- |
| `external` | 真实第三方程序执行；必须声明依赖 |
| `internal_approximation` | 内置近似模型代替真实程序；**结果必须标注为近似** |
| `synthetic_demo` | 基于合成数据的演示输出；**不代表真实测量** |

> ⚠️ `internal_approximation` / `synthetic_demo` 的结果**不得**表述为第三方科研软件的真实计算，
> 也不得作为科研准确率声明。

## 状态汇总（运行时探测）

| 状态 | 节点数 |
| --- | --- |
| `executable` | 87 |
| `experimental` | 5 |
| `unavailable` | 9 |

## capability_status 汇总（v0.7.2）

| capability_status | 节点数 |
| --- | --- |
| `executable` | 87 |
| `experimental` | 1 |
| `unavailable` | 9 |
| `verified` | 4 |

## execution_mode 汇总（v0.7.2）

| execution_mode | 节点数 |
| --- | --- |
| `internal_approximation` | 101 |

## 可复现级别汇总（v0.7.2）

| reproducibility_level | 节点数 |
| --- | --- |
| `deterministic` | 99 |
| `nondeterministic` | 2 |

## 能力汇总

| 能力标签 | 节点数 |
| --- | --- |
| `deduces_fragmentation_pathway` | 1 |
| `experimental` | 14 |
| `models_double_sei_energetics` | 1 |
| `models_electrolyte_aging` | 1 |
| `models_nanopore_desolvation` | 1 |
| `models_pre_desolvation_mechanism` | 1 |
| `models_seismic_forward` | 2 |
| `models_seismic_fwi` | 1 |
| `models_seismic_submission` | 1 |
| `nondeterministic` | 2 |
| `requires_external_software` | 10 |
| `requires_gpu` | 4 |
| `requires_network` | 15 |
| `sensitive_data` | 1 |
| `writes_files` | 4 |

## 全部节点

| 节点类型 | 分类 | 状态 | capability_status | execution_mode | 可复现 | 验证证据 | 能力标签 | 依赖外部软件 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `ChemBERTaNode` | AI/Foundation Models | `experimental` | `executable` | `internal_approximation` | 是 | — | `experimental` | — |
| `GROVERNode` | AI/Foundation Models | `experimental` | `executable` | `internal_approximation` | 是 | — | `experimental` | — |
| `GraphormerNode` | AI/Foundation Models | `experimental` | `executable` | `internal_approximation` | 是 | — | `experimental` | — |
| `UniMolNode` | AI/Foundation Models | `experimental` | `executable` | `internal_approximation` | 是 | — | `experimental` | — |
| `LLMNode` | AI/LLM | `executable` | `executable` | `internal_approximation` | 是 | — | `requires_network`, `sensitive_data` | — |
| `PropertyPredictionNode` | AI/ML | `executable` | `executable` | `internal_approximation` | 是 | — | — | — |
| `SimilaritySearchNode` | AI/ML | `executable` | `executable` | `internal_approximation` | 是 | — | — | — |
| `TrainModelNode` | AI/ML | `executable` | `executable` | `internal_approximation` | 否 | — | `nondeterministic` | — |
| `VisionNode` | AI/Vision | `executable` | `executable` | `internal_approximation` | 是 | — | — | — |
| `AgentPlanNode` | Agent | `executable` | `executable` | `internal_approximation` | 是 | — | — | — |
| `ScientificAgentNode` | Agent | `executable` | `executable` | `internal_approximation` | 是 | — | — | — |
| `ReportAgentNode` | Agent/Reporting | `executable` | `executable` | `internal_approximation` | 是 | — | `writes_files` | — |
| `BaselineCorrectionNode` | Analysis | `executable` | `executable` | `internal_approximation` | 是 | — | — | — |
| `FunctionalGroupNode` | Analysis | `executable` | `executable` | `internal_approximation` | 是 | — | — | — |
| `MolecularDescriptorsNode` | Analysis | `executable` | `executable` | `internal_approximation` | 是 | — | — | — |
| `NormalizeNode` | Analysis | `executable` | `verified` | `internal_approximation` | 是 | 2 | — | — |
| `PeakPickingNode` | Analysis | `executable` | `verified` | `internal_approximation` | 是 | 2 | — | — |
| `ProfileCentroidNode` | Analysis | `executable` | `executable` | `internal_approximation` | 是 | — | — | — |
| `ResampleNode` | Analysis | `executable` | `executable` | `internal_approximation` | 是 | — | — | — |
| `SimilarityNode` | Analysis | `executable` | `executable` | `internal_approximation` | 是 | — | — | — |
| `SmoothingNode` | Analysis | `executable` | `verified` | `internal_approximation` | 是 | 1 | — | — |
| `SpectrumMathNode` | Analysis | `executable` | `executable` | `internal_approximation` | 是 | — | — | — |
| `SubstructureSearchNode` | Analysis | `executable` | `executable` | `internal_approximation` | 是 | — | — | — |
| `FragmentationPathwayNode` | Analysis/Mass Spectrometry | `executable` | `executable` | `internal_approximation` | 是 | — | `deduces_fragmentation_pathway` | — |
| `ChEMBLNode` | Databases/Chemical | `executable` | `executable` | `internal_approximation` | 是 | — | `requires_network` | — |
| `PDBNode` | Databases/Chemical | `executable` | `executable` | `internal_approximation` | 是 | — | `requires_network` | — |
| `PubChemNode` | Databases/Chemical | `executable` | `executable` | `internal_approximation` | 是 | — | `requires_network` | — |
| `ZINCNode` | Databases/Chemical | `executable` | `executable` | `internal_approximation` | 是 | — | `requires_network` | — |
| `AFLOWNode` | Databases/Materials | `executable` | `executable` | `internal_approximation` | 是 | — | `requires_network` | — |
| `CODNode` | Databases/Materials | `executable` | `executable` | `internal_approximation` | 是 | — | `requires_network` | — |
| `ICSDNode` | Databases/Materials | `executable` | `executable` | `internal_approximation` | 是 | — | `requires_network` | — |
| `MaterialsProjectNode` | Databases/Materials | `executable` | `executable` | `internal_approximation` | 是 | — | `requires_network` | — |
| `BMRBNode` | Databases/Spectral | `executable` | `executable` | `internal_approximation` | 是 | — | `requires_network` | — |
| `GNPSNode` | Databases/Spectral | `executable` | `executable` | `internal_approximation` | 是 | — | `requires_network` | — |
| `HMDBNode` | Databases/Spectral | `executable` | `executable` | `internal_approximation` | 是 | — | `requires_network` | — |
| `MassBankNode` | Databases/Spectral | `executable` | `executable` | `internal_approximation` | 是 | — | `requires_network` | — |
| `MoNANode` | Databases/Spectral | `executable` | `executable` | `internal_approximation` | 是 | — | `requires_network` | — |
| `NISTNode` | Databases/Spectral | `executable` | `executable` | `internal_approximation` | 是 | — | `requires_network` | — |
| `GpuDeviceInfoNode` | GPU | `executable` | `executable` | `internal_approximation` | 是 | — | `requires_gpu` | — |
| `InferenceBenchmarkNode` | GPU | `executable` | `executable` | `internal_approximation` | 否 | — | `requires_gpu`, `nondeterministic` | — |
| `ModelInferenceNode` | GPU | `executable` | `executable` | `internal_approximation` | 是 | — | `requires_gpu` | — |
| `PyTorchTensorOpNode` | GPU | `executable` | `executable` | `internal_approximation` | 是 | — | `requires_gpu` | — |
| `ExportNode` | IO | `executable` | `executable` | `internal_approximation` | 是 | — | `writes_files` | — |
| `ImageFileNode` | IO | `executable` | `executable` | `internal_approximation` | 是 | — | — | — |
| `MaterialInputNode` | IO | `executable` | `executable` | `internal_approximation` | 是 | — | — | — |
| `MoleculeInputNode` | IO | `executable` | `verified` | `internal_approximation` | 是 | 2 | — | — |
| `SpectrumFileNode` | IO | `executable` | `executable` | `internal_approximation` | 是 | — | — | — |
| `TableFileNode` | IO | `executable` | `executable` | `internal_approximation` | 是 | — | — | — |
| `TextInputNode` | IO | `executable` | `executable` | `internal_approximation` | 是 | — | — | — |
| `VendorSpectrumNode` | IO | `executable` | `executable` | `internal_approximation` | 是 | — | — | — |
| `SingleCrystalXRDNode` | Instruments/Diffraction | `executable` | `executable` | `internal_approximation` | 是 | — | — | — |
| `XRDNode` | Instruments/Diffraction | `executable` | `executable` | `internal_approximation` | 是 | — | — | — |
| `CVNode` | Instruments/Electrochemistry | `executable` | `executable` | `internal_approximation` | 是 | — | — | — |
| `DesolvationSieveNode` | Instruments/Electrochemistry | `executable` | `executable` | `internal_approximation` | 是 | — | `models_nanopore_desolvation` | — |
| `DoubleSEIEnergeticsNode` | Instruments/Electrochemistry | `executable` | `executable` | `internal_approximation` | 是 | — | `models_double_sei_energetics` | — |
| `EISNode` | Instruments/Electrochemistry | `executable` | `executable` | `internal_approximation` | 是 | — | — | — |
| `ElectrolyteAgingNode` | Instruments/Electrochemistry | `executable` | `executable` | `internal_approximation` | 是 | — | `models_electrolyte_aging` | — |
| `PreDesolvationMechanismNode` | Instruments/Electrochemistry | `executable` | `executable` | `internal_approximation` | 是 | — | `models_pre_desolvation_mechanism` | — |
| `FluorescenceNode` | Instruments/Electronic | `executable` | `executable` | `internal_approximation` | 是 | — | — | — |
| `UVVisNode` | Instruments/Electronic | `executable` | `executable` | `internal_approximation` | 是 | — | — | — |
| `FTIRImagingNode` | Instruments/Imaging | `executable` | `executable` | `internal_approximation` | 是 | — | — | — |
| `HyperspectralNode` | Instruments/Imaging | `executable` | `executable` | `internal_approximation` | 是 | — | — | — |
| `RamanMappingNode` | Instruments/Imaging | `executable` | `executable` | `internal_approximation` | 是 | — | — | — |
| `GCMSNode` | Instruments/Mass Spectrometry | `executable` | `executable` | `internal_approximation` | 是 | — | — | — |
| `ICPMSNode` | Instruments/Mass Spectrometry | `executable` | `executable` | `internal_approximation` | 是 | — | — | — |
| `LCMSNode` | Instruments/Mass Spectrometry | `executable` | `executable` | `internal_approximation` | 是 | — | — | — |
| `MALDINode` | Instruments/Mass Spectrometry | `executable` | `executable` | `internal_approximation` | 是 | — | — | — |
| `AFMNode` | Instruments/Microscopy | `executable` | `executable` | `internal_approximation` | 是 | — | — | — |
| `SEMNode` | Instruments/Microscopy | `executable` | `executable` | `internal_approximation` | 是 | — | — | — |
| `TEMNode` | Instruments/Microscopy | `executable` | `executable` | `internal_approximation` | 是 | — | — | — |
| `NMRNode` | Instruments/NMR | `executable` | `executable` | `internal_approximation` | 是 | — | — | — |
| `BETNode` | Instruments/Particle | `executable` | `executable` | `internal_approximation` | 是 | — | — | — |
| `DLSNode` | Instruments/Particle | `executable` | `executable` | `internal_approximation` | 是 | — | — | — |
| `FWIInversionNode` | Instruments/Seismic | `executable` | `executable` | `internal_approximation` | 是 | — | `models_seismic_fwi` | — |
| `SeismicForwardNode` | Instruments/Seismic | `executable` | `executable` | `internal_approximation` | 是 | — | `models_seismic_forward` | — |
| `SeismicSubmissionNode` | Instruments/Seismic | `executable` | `executable` | `internal_approximation` | 是 | — | `models_seismic_submission` | — |
| `SeismicSurveyNode` | Instruments/Seismic | `executable` | `executable` | `internal_approximation` | 是 | — | `models_seismic_forward` | — |
| `XASNode` | Instruments/Surface | `executable` | `executable` | `internal_approximation` | 是 | — | — | — |
| `XASSim2RealNode` | Instruments/Surface | `executable` | `executable` | `internal_approximation` | 是 | — | — | — |
| `XPSNode` | Instruments/Surface | `executable` | `executable` | `internal_approximation` | 是 | — | — | — |
| `DMANode` | Instruments/Thermal | `executable` | `executable` | `internal_approximation` | 是 | — | — | — |
| `DSCNode` | Instruments/Thermal | `executable` | `executable` | `internal_approximation` | 是 | — | — | — |
| `TGANode` | Instruments/Thermal | `executable` | `executable` | `internal_approximation` | 是 | — | — | — |
| `IRNode` | Instruments/Vibrational | `executable` | `executable` | `internal_approximation` | 是 | — | — | — |
| `RamanNode` | Instruments/Vibrational | `executable` | `executable` | `internal_approximation` | 是 | — | — | — |
| `MaterialDiscoveryNode` | Questions | `executable` | `executable` | `internal_approximation` | 是 | — | — | — |
| `UnknownCompoundIdentificationNode` | Questions | `executable` | `executable` | `internal_approximation` | 是 | 3 | — | — |
| `FigureExportNode` | Report | `executable` | `executable` | `internal_approximation` | 是 | — | `writes_files` | — |
| `ReportBuilderNode` | Report | `executable` | `executable` | `internal_approximation` | 是 | — | — | — |
| `ReportExportNode` | Report | `executable` | `executable` | `internal_approximation` | 是 | — | `writes_files` | — |
| `SummaryTableNode` | Report | `executable` | `executable` | `internal_approximation` | 是 | — | — | — |
| `GROMACSNode` | Simulation/MD | `unavailable` | `unavailable`（已降级） | `internal_approximation` | 是 | — | `requires_external_software`, `experimental` | `gmx`（缺失：`gmx`） |
| `LAMMPSNode` | Simulation/MD | `unavailable` | `unavailable`（已降级） | `internal_approximation` | 是 | — | `requires_external_software`, `experimental` | `lmp`（缺失：`lmp`） |
| `OpenMMNode` | Simulation/MD | `experimental` | `experimental` | `internal_approximation` | 是 | — | `requires_external_software`, `experimental` | `python` |
| `ABACUSNode` | Simulation/Materials | `unavailable` | `unavailable`（已降级） | `internal_approximation` | 是 | — | `requires_external_software`, `experimental` | `abacus`（缺失：`abacus`） |
| `QuantumESPRESSONode` | Simulation/Materials | `unavailable` | `unavailable`（已降级） | `internal_approximation` | 是 | — | `requires_external_software`, `experimental` | `pw.x`（缺失：`pw.x`） |
| `VASPNode` | Simulation/Materials | `unavailable` | `unavailable`（已降级） | `internal_approximation` | 是 | — | `requires_external_software`, `experimental` | `vasp_std`（缺失：`vasp_std`） |
| `CP2KNode` | Simulation/Quantum | `unavailable` | `unavailable`（已降级） | `internal_approximation` | 是 | — | `requires_external_software`, `experimental` | `cp2k.psmp`（缺失：`cp2k.psmp`） |
| `GaussianNode` | Simulation/Quantum | `unavailable` | `unavailable`（已降级） | `internal_approximation` | 是 | — | `requires_external_software`, `experimental` | `g16`（缺失：`g16`） |
| `ORCANode` | Simulation/Quantum | `unavailable` | `unavailable`（已降级） | `internal_approximation` | 是 | — | `requires_external_software`, `experimental` | `orca`（缺失：`orca`） |
| `Psi4Node` | Simulation/Quantum | `unavailable` | `unavailable`（已降级） | `internal_approximation` | 是 | — | `requires_external_software`, `experimental` | `psi4`（缺失：`psi4`） |
