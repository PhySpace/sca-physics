# SCA 物理属性附加插件 0.1.8rc1

独立 SCA add-on，在建模和 capture **之后**读取 `.scadpkg`，校验并将下游物理声明保存到根定义 `metadata.sca_physics`。通过 SCA 正式产品包 API 保存、重新读取完整产品包；几何、原生材料、装配连接、历史和已有 scene 必须保持。当前候选配套为 `sca-physics==0.1.8rc1` 与 `sca-usd-export==0.1.8rc2`。纯几何导出不需要安装物理插件；导出包内物理配置时，导出器需要其可选 `physics` 依赖。

本仓库根就是可修改、可安装项目。安装 payload、运行环境和注册后的 skill 是独立副本，修改本仓库不会自动更新它们。

Schema **1.8** 增加绑定原生 joint_id 的自由/有限运动、SI 限位、最大速度、关节摩擦、off/position/velocity 的 force 执行器、Articulation 请求与最小旋转→移动理想 Mimic 齿轮齿条耦合。原生父子连接器、局部坐标、轴、零位与正方向不由插件覆盖。公开 `update_config` / `update_package` 和命令 `update` 支持有来源的部分更新，不重置其他显式参数、不替新值沿用旧来源。含新增字段时默认使用1.8；没有新增字段的配置继续1.7。字段、SI单位、被动/主动阻尼组合、float32检查及后端限制见 [关节参数与主动驱动](docs/joint-physics.zh-CN.md)。

历史0.1.6rc1的安装、保存/回读、V6回归及通用结构检查通过，但**定量分段一致性与扭转理论检查失败**。保持EI/GJ不变的20/40/80段响应明显软化，原记录继续保留。0.1.6rc2区分高步频合同、修正配套TGS外力子步策略并补充长度/准静态诊断；软件修复本身不等于工程精度或实物标定通过。见 [验证范围](docs/validation.zh-CN.md)。

上一阶段0.1.6rc2新隔离安装的软件测试243项通过、2项外部CAD-FEM fixture未提供而跳过；历史rc1另有真实旧CAD-FEM包13/13记录，本轮不冒称重跑。软件、产品包检查不能代替单独的定量力学验收。

## Agent 决策、来源与自动分段

没有新增关节/Articulation/耦合字段的新写入使用 Schema **1.7**；含这些字段时使用 **1.8**。Agent 先依据构造、尺寸、用途和资料选择受支持的表示与物性，再将决定连同来源交给插件；程序不承担通用自然语言分类，不把未知描述默认为电线。`configure-cable` 必须显式选择 `stranded_wire` 或 `pvc_jump_rope`。不匹配这两类但满足圆截面、平面初态、直线自然态的对象，使用完整 `set-rigid-chain` 声明。

提交的合法 `properties` 优先于 `evidence`，预设只补缺；Agent 的 estimated 线密度/EI/GJ 不再被 preset 覆盖。每个输入值必须有逐字段来源或继承组/声明来源；裸值无来源则拒绝并指出字段，不自动冒称用户输入。显式 0/false 保留。公开 `circle_rod` 将有来源的 d、ρ、E、G 换算为 λ、EI、GJ，保存受支持规则、固定公式与实际输入，独立回读重算核对。详见 [Agent 决策与来源](docs/agent-decisions.zh-CN.md)。

```text
configure-cable raw.scadpkg --target 实际node_id --config 已注明category和来源的请求.json --output final.scadpkg
cable-presets
```

自动入口保存实际几何、最终 N、解析请求、预设/规则版本、来源、预算及未验证范围。明确段数、目标段长、自动模式互斥，超预算报错而不截断。旧 Schema1.0–1.6 产品包原样读/导出，不重新选段或改写旧来源；显式重配置从已保存的实际 wrapper 继续，仅新提交的同名值替换。新版本不自动把历史包的来源问题改写成新事实。

独立导出只消费最终包；Agent 查资料与插件运行分开。自动选段是初始工程规则，不是动作适应、材料标定或收敛证明。使用方式和边界见 [自动线缆](docs/automatic-cables.zh-CN.md)。

## 已实现的接口与限制

- 保留 schema 1.0/1.1 的接触、碰撞、实例模式、重力、阻尼、偏置、组合规则、过滤和被动关节阻尼；显式 0/false、来源、SI 单位、engine_default 语义保持。
- 保留 schema 1.2/1.3 的 FEM 声明、CAD occurrence 身份、官方网格缓存和材料更新。保存成功不代表 FEM 行为通过，已有细长线缆失败结论继续保留。
- 新增 schema **1.4**，以 `cables[id].representation` 区分 `physx_deformable_volume` 和 **`rigid_joint_chain`**；命令 `set-rigid-chain` 持久化圆截面刚体关节链声明。配套 USD 插件派生分段、质量/惯量、D6、端部连接和接触设置。本插件不创建 USD、不实现求解器。
- 0.1.6rc2 新增 schema **1.5**，仅把刚体链 `scene.physics_hz` 上限提高至 **16384**；高于4096Hz的新声明选择1.5，该历史版本的低Hz新链和既有1.4包保持1.4；当前新写入统一为1.7。旧1.4仍拒绝高于4096Hz的值。分段2..512、solver iterations不超过255及旧Schema全部保留；高步频可保存不等于力学精度已经通过。
- 刚体链首版支持世界 SI 中心线、平面初态、直线自然参考、圆主截面和端部半径、每关节阻尼；端点为 free/world_fixed/body_fixed。扁截面、分叉、多芯内部结构、空间初态、弯曲自然态和分布阻尼明确拒绝。
- 参数保留来源；新描述入口采用版本化类别预设和明确的整线工程估计，不能由“充电线”名称或图片声称推导实测 EI/GJ/阻尼。平移锁定不等于连续体拉伸本构；初始曲线相对直线自然参考会回弹。

建模时同步声明的 PhysicsDocument 属于另行保留的 0.1.3/0.1.4/0.2 开发线，此仓库没有合入这些接口，也不提供原生 GUI 物理面板。

## 安装与使用

要求 Windows x86-64、CPython 3.12、SCA `>=2.2.5,<2.2.6`；runtime.check 当前只认可 SCA 2.2.5。以独立 add-on home、skills-dir 和 runtime 安装本仓库根，详见 [安装说明](docs/installation.zh-CN.md)。不要将依赖装入建模宿主，也不要复用其他候选的安装副本。

独立 runtime 的实际入口为 `python -I -B -m sca_physics`，或console script `sca-physics`：

```text
check
inspect 输入.scadpkg
template 输入.scadpkg --include-mechanical --output 新配置.json
enrich 输入.scadpkg --config 配置.json --output 新包.scadpkg
update 已有物理包.scadpkg --config 部分更新.json --output 更新后.scadpkg
validate 新包.scadpkg --expect 独立完整期望.json
set-deformable ...
set-rigid-chain 输入.scadpkg --target 精确node_id --config 声明.json --output 新包.scadpkg
```

inspect提供实际occurrence ID，不能按显示名或导出后的哈希路径选择。已有包允许显式完整配置经enrich另存，省略配置的重复enrich仍拒绝；输出独占创建，不能覆盖历史文件。刚体链初次附加可使用 `--base-config`，仅限没有sca_physics的raw包；转换所选既有刚体/FEM需分别明确 `--convert-rigid` / `--replace-deformable`。

字段、API与限制见 [刚体关节链](docs/rigid-joint-chains.md)、[旧字段](skill/references/physics-format.md)、[CAD FEM](docs/cad-deformables.md)。完整最小线缆命令见 [圆线缆示例](examples/rigid_chain/README.md)；旧CAD示例在 `examples/pendulum/`、`examples/mechanical_v1_1/`。完整V6的CAD、驱动、native runner、结果和ZIP留在独立项目，没有复制进插件。

开发安装 `.[test]` 后，在已安装runtime执行 `python -I -B -m pytest tests -p no:cacheprovider`；jsonschema检查不能跳过。`verification/raw.scadpkg`和`verification/rigid-chain-raw.scadpkg`是约290/116KiB的真实回归fixture，应保留。真实FEM用例 `tests/test_cad_deformable.py --package 实际包` 与原生行为分别验证，未提供参数的跳过要报告。`scripts/verify_postattach.py`是需USD/numpy及显式项目资产的集成检查，不是基础运行依赖。

更多见 [验证范围](docs/validation.zh-CN.md)、[来源与许可证](docs/provenance.zh-CN.md)。不分发SCA/Isaac/PhysX二进制或第三方依赖源码。

候选发布环境、兼容性范围、升级顺序与未验证项见 [本地发布准备](docs/release-candidate.zh-CN.md)；本轮变更见 [更新记录](CHANGELOG.zh-CN.md)。旧包读取支持不等于所有历史输入参数无需迁移：新提交的无来源裸值、缺 category 的自动配置及错误的 FEM 阻尼单位会明确拒绝。

## 当前候选的兼容与升级结论

实际验证配对仅为 **physics 0.1.8rc1 + USD 0.1.8rc2**，环境为 Windows x86-64、Python 3.12.15、SCA SDK 2.2.5、OpenUSD（usd-core）26.8、OCP（cadquery-ocp）7.9.3.1；OpenUSD 来自隔离 venv。所选旧包是 2026-10-19 physics 0.1.0/schema 1.0 摆臂包（SHA256 `ba39ea3d58fbe8c59ca00153858fd72d6d00f091f71602374461ec6c7f4406ec`）和 2026-10-20 physics 0.1.3rc1/schema 1.1 机械包（`54f37bbfd0576d88a2d7f7a718718fce0fa29cf8e3540601b3e1fcc29caf8893`）。两者均经过 SDK 原生加载、编码重载、物理快照保持及 USD 导出/重开；确切输入路径、producer 证据和旧路径/内存 API 范围见 [兼容性表](docs/release-candidate.zh-CN.md#兼容性合同及迁移)。

**旧无来源裸参数原样不兼容；按要求补充来源信息后，所测试案例通过。** 归档 `collision_enabled=false` 须增加真实来源；[随包摆臂输入](examples/pendulum/physics-input.json) 已保留 false/schema 1.0 并注明软件试验估计，运行命令见 [迁移示例](docs/release-candidate.zh-CN.md#来源迁移的可运行例子)。真实产品须说明实际依据；不能抄例子来源冒充测量或用户输入。source 可置于字段、组或声明根，`reference` 须带 detail/citation/conditions。

必需运行依赖只有 SimpleCADAPI；hatchling 属于构建、pytest/jsonschema 属于开发测试，Isaac/PhysX 属于外部仿真验证环境。本插件不导入 USD；导出端既读取包内数据，也直接调用本插件的合同/几何模块，所以含物理配置时必须满足其可选 `physics` extra 的精确 pin。无嵌入物理配置时可只升级 USD；已有 physics 0.1.8rc1 可保持版本，仅更新并重新 provision USD 0.1.8rc2。较旧物理用户先准备并检查匹配导出器/依赖，再切换 physics 写入入口；建议新 home 安装整组后切换。缺失/错配会明确报错，不默默忽略配置。

Windows 须选较短的新安装状态/runtime 根；已测 `personal-workspace/results/arp-20261025-162555/s`（独立 USD）与 `p`（配对），其下 `a` 为 home、`s` 为 skills、`runtimes` 为解释器目录。深路径安装 Jedi 失败的问题仍保留。**两项外部 FEM 检查、Isaac／PhysX 行为、其他环境、全部历史版本组合均未验证**；候选安装和导出通过不等于物理仿真行为全面通过。
