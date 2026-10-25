# 本地候选发布范围（2026-10-25）

候选为 **sca-physics 0.1.8rc1**，职责是校验并保存产品包根定义 `metadata.sca_physics`，不创建 USD、不实现求解器。配套候选为 **sca-usd-export 0.1.8rc2**。本地发布准备运行标识为 `20261025_162555`；完整 `REPORT.zh-CN.md`、`REPRODUCE.zh-CN.md`、安装包哈希与逐命令日志归档到工作区 `results/addon-release-preparation/<运行标识>/`。本页说明交付合同，实际执行结果以该报告为准。

后续候选提交审查归档为 `results/addon-github-candidate/20261025_172250/`：补齐本页兼容说明，并修正公开Agent示例仍要求旧0.1.7rc2配对的版本守卫。wire与spring-wire两条静态软件链路均重新运行通过；`src`物理实现、schema和依赖不因该例子修复而改变。文档与例子修正后的最终ZIP须采用该次归档的新哈希，不能沿用前次包哈希。

版本沿用此前未发布的0.1.8rc1，原因是本轮未改变物理实现、元数据schema或API签名。导出器独立调整候选号以区分其依赖/安装修正。候选状态不等于正式发布或完整力学验收。

## 环境、依赖与安装

声明环境为 Windows x86-64、CPython `>=3.12,<3.13`、SimpleCADAPI `>=2.2.5,<2.2.6`；runtime probe只认可实测过的SCA2.2.5。实际配套验证为 **physics0.1.8rc1 / USD0.1.8rc2、Windows x86-64、Python3.12.15、SCA SDK2.2.5、OpenUSD（usd-core）26.8/API(0,26,8)、OCP（cadquery-ocp）7.9.3.1**，另有NumPy2.3.1、Plotly7.1.0。OpenUSD从新隔离venv加载，没有借用Isaac的pxr。不是所有候选组合或其他环境的保证。

物理插件唯一直接运行依赖是simplecadapi；hatchling是构建依赖，pytest与jsonschema属于test extra。Isaac Sim、PhysX、OpenUSD和numpy不是本插件直接必需依赖；可选集成探针按对应项目提供环境。

本插件不导入USD插件。USD插件在没有物理配置的几何路径中不需要本插件；消费嵌入物理配置、FEM或刚体链时，其可选 `physics` extra需要精确的 `sca-physics==0.1.8rc1`，实际代码会调用本插件的合同/几何校验，而非只共享JSON名称。物理数据版本与Python插件版本是两个不同概念，不能只因扩展名相同就认为兼容。

SCA add-on使用带根目录 `sca-addon.toml`、`pyproject.toml`、`src`、`scripts`、`skill`及其资源的安装包；Python wheel单独安装不会登记add-on/skill。使用官方 `addon add` 注册已解包候选根目录，再 `addon use ... provision` 创建该home独立runtime，最后 `addon check`并检查registry中的 `runtime_check.passed`。本机SDK当前接受的包来源与完整隔离命令见[安装说明](installation.zh-CN.md)和外部复现报告；不得假设ZIP本身就是CLI认可的来源类型。

隔离验收必须在专用子进程重定向USERPROFILE、APPDATA和LOCALAPPDATA；仅设置home/skills-dir不能避免SCA写用户配置。不要改变现用stable或全局技能。源码、安装payload、site-packages和skill是不同副本，核对真正的module origin；不以editable安装代替交付包验证。

本机长路径结果目录中的USD首次provision因SCA传递依赖Jedi的深层文件路径超限失败。未启用Windows长路径支持时，应为安装状态及runtime选择较短的新路径；日志可另存完整归档目录。本轮不修改系统注册表或SDK，也不据单个成功路径推导通用长度保证。

已验证的短状态根为 `personal-workspace/results/arp-20261025-162555/s`（未安装physics的独立USD）和 `personal-workspace/results/arp-20261025-162555/p`（配对）；各自的 `a` 是add-on home、`s` 是skills-dir、`runtimes/<插件名>/.venv` 是独立解释器。它们是相对工作区的实测路径示例，不是跨机器固定路径；重现须选择新的同等简短路径，不复用旧状态或覆盖稳定安装。

## 兼容性合同及迁移

`inventory(package)`、`resolve_config(package, input_dict=None)`、`validate_config(package, config)`和 `enrich_package(package, config=None)`保持原公开调用形式。`template`仍输出显式Schema1.0，`template --include-mechanical`仍输出显式1.1；`inspect`、`enrich`、`validate --expect`、`set-deformable`和 `set-rigid-chain`入口保留。新增 `update_config` / `update_package`用于有来源的部分更新。已有物理包无配置重复enrich仍拒绝，输出仍要求新路径。

| 情况 | 当前合同与迁移 |
|---|---|
| 旧Schema1.0–1.6完整产品包 | 保留只读校验路线；不自动升级来源、重选段数或改值。实际回归范围必须看输入哈希与本轮日志，不能据合同宣称全部历史版本均已验证。 |
| 新输入未指定schema | 基础/线缆默认1.7；新增关节、Articulation或耦合字段选择1.8。要保持旧写入格式，显式选择1.0/1.1，并只用该版本字段。 |
| 旧裸值或不完整wrapper没有来源 | 当前新提交会明确拒绝，含显式旧schema的请求也不例外。给字段、最近组或声明根补真实source；估计写estimated，用户确实指定才写explicit。不能改写旧包来源冒称新事实。 |
| 旧自动线缆请求仅有description | 必须显式提供 `stranded_wire` 或 `pvc_jump_rope` category；其他受支持圆细长体提交完整set-rigid-chain。description不再兜底分类为电线。 |
| FEM elasticity_damping显式unit为1 | 当前要求1/s，拒绝错单位。确认原数值含义后另存新配置；不自动乘除比例，不覆盖原包。 |
| 显式旧schema混入1.8关节字段 | 拒绝；采用支持1.8的配套导出器后用正确schema另存。不能仅降低schema标签。 |

以下路径相对 `personal-workspace/`，旧输入原件保持不变。下表两个包均验证了 `read_product_package`、`load_product_package`、编码后重载、完整物理快照保持、USD导出及重开。

| schema / 真实producer | 具体输入与SHA256 | producer证据 |
|---|---|---|
| 1.0；2026-10-19 physics0.1.0 / SDK2.2.5 | `results/sca-physics/20261019_stable_coexistence_184500/validation/final.scadpkg`；`ba39ea3d58fbe8c59ca00153858fd72d6d00f091f71602374461ec6c7f4406ec` | 同次运行`restored-baseline-manifest.json`冻结版本；证据SHA256 `ac0bbc52b02e0c4a8d59f06f86cf1c71f504360098bf250ab6a2a5ce8d6e435b` |
| 1.1；2026-10-20 physics0.1.3rc1 / SDK2.2.5 | `results/sca-physics/20261020_authoring_mvp_0_1_3rc1/legacy-flow/attempt-02/mechanical.scadpkg`；`54f37bbfd0576d88a2d7f7a718718fce0fa29cf8e3540601b3e1fcc29caf8893` | 同目录`check-physics.stdout.log`记录实际插件版本；证据SHA256 `2371d28d0a18a579779d26caa5c48c2baba7caba9f5a301a8419e96886da119f` |

包内generator均指向SCA2.2.5，producer由上述历史证据确认，不由文件名或扩展名猜测。0.1.3rc1的同步authoring建模入口不属于本仓库；读取其已有1.1产品包不能扩大成支持其建模API。其他schema1.2–1.6真实历史成品包未在本轮逐一实跑。

旧路径/内存API实测为导出端 `export_package(path, output, config=ExportConfig.from_json(...))` 与 `export_package(ProductPackage, output, config=ExportConfig(...))`，采用冻结本机0.1.0的已有配置字段和值。physics旧 `inventory`、`resolve_config`、`validate_config`、`enrich_package` 签名经AST对照保持，CLI `template/enrich/validate --expect`实际通过；不能扩成所有旧参数分支都已运行。更早GitHub导出源码 `9fa527b` 的缺省方向/恢复系数为Y/0，当前和本机冻结0.1.0为Z/0.1；要保留该更早行为须显式设置方向与接触配置，未实际安装验证该GitHub提交。

### 来源迁移的可运行例子

**旧无来源裸参数原样不兼容；按要求补充来源信息后，所测试案例通过。** 归档0.1.0的`examples/pendulum/physics-input.json`（SHA256 `60893a0ab782714dc26ed11fec90e5885fa10a43a2382c12099ca3988312d480`）中，`joints["joint/passive_pendulum/hinge"].collision_enabled=false`原样被拒绝并提示`.source: required`。本轮只为该字段补充真实的`value/unit/source`，保持false和schema1.0后，完整附加、重载、导出流程通过；当前[随包示例](../examples/pendulum/physics-input.json)已采用相同迁移方式，并通过真实产品包测试。

```json
{"value": false, "unit": "boolean", "source": {"kind": "estimated", "detail": "Software fixture deliberately disables collision between the hinge bodies; not a measured property"}}
```

这是软件试验的实际估计，不能拿来证明真实产品的碰撞需求。实际迁移须保持原值与单位，用字段source或最近组/声明根source说明真实依据：用户确实指定才用explicit；工程假设用estimated并写清依据、适用条件；资料用reference，必须填写真实detail/citation/conditions。未知来源应先核实或省略可选新字段，不能为过校验编造出处。已保存历史包的只读校验不重写来源。

使用已登记候选的`$PhysicsPython`、`$UsdPython`以及实际physics安装`$RepoRoot`，在全新`$Run`目录运行（各路径先按自己的安装设置；失败即停止）：

```powershell
& $PhysicsPython -I -B -m sca_physics enrich "$RepoRoot/verification/raw.scadpkg" --config "$RepoRoot/examples/pendulum/physics-input.json" --output "$Run/migrated.scadpkg"
& $PhysicsPython -I -B -m sca_physics validate "$Run/migrated.scadpkg"
& $UsdPython -I -B -m sca_usd_export export "$Run/migrated.scadpkg" "$Run/migrated.usda" --require-physics
& $UsdPython -I -B -m sca_usd_export validate "$Run/migrated.usda"
```

## 升级与最小复现

无嵌入物理配置的纯几何用户只升级USD即可；实际验证其runtime中没有sca_physics模块或distribution，并保留导出器原有legacy默认物理描述。已有physics0.1.8rc1者保留它，更新并重新provision USD0.1.8rc2。较旧物理用户若走本候选物理导出，需配套升级：先明确选择physics0.1.8rc1源或wheel，准备USD0.1.8rc2及其匹配依赖并check，再切换physics0.1.8rc1写入入口，最后才写新的1.8声明；也可在全新home一次安装候选配对后切换。两个独立runtime都要核实实际版本及来源，不共用旧runtime或源码注入。

导出器缺物理模块时给出需要可选`sca-physics==0.1.8rc1`及provision准备方式的错误；错版本明确报告mismatch；未知schema明确拒绝。实际选择归档physics0.1.0源provision返回2且不写ready receipt，受控进程错配与schema9.9负例均无残留USD。未验证旧导出器读取新1.8，不能先升级写入端并假定旧读取端能忽略新字段；也不能仅改schema标签绕过检查。

安装后，用随包小型fixture在新输出目录执行以下命令；`$PhysicsPython`、`$UsdPython`指向已登记候选的独立解释器，`$RepoRoot`指向实际安装payload，`$Run`指向新结果目录：

```powershell
& $PhysicsPython -I -B -m sca_physics check
& $PhysicsPython -I -B -m sca_physics template "$RepoRoot/verification/raw.scadpkg" --output "$Run/legacy-template.json"
& $PhysicsPython -I -B -m sca_physics enrich "$RepoRoot/verification/raw.scadpkg" --config "$Run/legacy-template.json" --output "$Run/final.scadpkg"
& $PhysicsPython -I -B -m sca_physics validate "$Run/final.scadpkg" --expect "$Run/legacy-template.json"
& $UsdPython -I -B -m sca_usd_export export "$Run/final.scadpkg" "$Run/final.usda"
& $UsdPython -I -B -m sca_usd_export validate "$Run/final.usda"
```

每条命令后核对退出码，失败停止；进一步核对实际物理值和保存报告的非物理语义保留标志。新1.8关节配置使用[关节示例](joint-physics.zh-CN.md)，刚体链使用[最小圆线缆](../examples/rigid_chain/README.md)。上述命令只验证软件链路与USD重开。

## 已知限制与未验证范围

运行环境和格式范围不扩到其他Python/SCA/平台。两项外部FEM检查未验证：`RealCADPackageTests.test_actual_brep_source_survives_complete_official_package_roundtrip`与`test_actual_selected_material_update_reuses_same_mesh_and_identity`，均因未传`--package`而跳过。Isaac／PhysX行为未验证，未运行仿真也未核实本轮求解版本。其他环境、全部历史版本组合、0.2 authoring框架和未标定材料均未验证。安装、保存/回读和静态USD导出通过不能描述成物理仿真行为全面通过。

源码回归为350通过/2跳过/1安装环境失败；候选wheel安装后单独补跑该新进程用例1通过，联合覆盖351项、2项未验证，不是一次完整安装suite全绿。本轮没有MJCF迁移、FEM算法修复、材料标定、长时视频或通用工程精度验收。历史失败与历史通过记录均保留，不能冒称本轮重跑。

候选核心代码及许可证为Apache-2.0，保留仓库LICENSE；不分发SCA/Isaac/PhysX或第三方依赖二进制。第三方运行依赖由各自分发包及许可证管理。两个历史Isaac探针的VERSION定位支持 `--isaac-root`，修改只影响环境记录，不改变物理条件；其真实仿真执行状态仍以本轮报告为准。
