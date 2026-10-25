# 按任务配置细长体与可复现选段（0.1.8rc1）

Agent 先理解物体构造、实际尺寸、用途、载荷、运动和接触需求，判断当前模型是否适用，再寻找匹配资料或形成有依据的工程估计。保留用户明确输入，记录假设、单位、来源和适用条件；可用可逆假设推进，关键模型或边界歧义需要澄清。几何建模和 capture 仍由 SCA 主流程完成，本插件保存与校验物理声明。

| 判断结果 | 当前可执行路径 |
|---|---|
| 对象与普通多股软电线/PVC跳绳预设匹配 | 显式选择 category，通过 configure-cable --config 提交请求，使用其确定性初始选段。 |
| 不匹配预设，但圆截面刚体链近似适用 | 使用 set-rigid-chain 完整声明，保留真实估计来源，并由调用者确定显式段数。 |
| 需要当前模型未实现的行为 | 说明缺口；仅在其他已实现表示满足其合同后采用，否则报告当前无法完成，不强行解释为电线。 |

Agent 可查资料并解释自然语言，本地小词表不承担通用语义理解。确定性计算、保存结果的校验及独立导出没有必需在线模型服务。输出是可调整的等效仿真初始配置，不是实物标定。

## 正式入口

先按 [安装说明](installation.zh-CN.md) 检查明确选择的候选 runtime。下述 $PhysicsPython/$UsdPython 必须分别属于 physics 0.1.8rc1 / USD 0.1.8rc2 的配套独立环境，不是默认 stable；node_id 取自 inspect，所有输出使用新路径。预设匹配且 CAD 为完整实心直圆柱时，可不手填中心线、长度、线径、段数、刚度或迭代数。request.json 例如：

```json
{"description":"做一根普通软电线","category":"stranded_wire","quality":"balanced","discretization":{"mode":"auto"}}
```

```powershell
& $PhysicsPython -I -B -m sca_physics cable-presets
& $PhysicsPython -I -B -m sca_physics inspect raw.scadpkg
& $PhysicsPython -I -B -m sca_physics configure-cable raw.scadpkg --target 'inspect得到的真实node_id' --config request.json --chain-id cable --output final.scadpkg
& $PhysicsPython -I -B -m sca_physics validate final.scadpkg
# 上一进程退出；只读取最终产品包，不传原中心线、预设文件或旧USD。
& $UsdPython -I -B -m sca_usd_export export final.scadpkg scene.usda
& $UsdPython -I -B -m sca_usd_export validate scene.usda
```

Windows也可通过各插件payload的 `scripts/use.ps1` 以参数数组调用上述命令；传入同一候选host/home/skills，不切换global stable。输出独占创建，不覆盖旧资产。

请求可另含端部或明确属性。以下是匹配 PVC 跳绳预设且确有两个独立手柄的请求示例，不是未知绳体的通用分类。`--description` 与文件描述不相同时拒绝，不能悄悄覆盖：

```json
{
  "description": "普通PVC跳绳，带两个手柄",
  "category": "pvc_jump_rope",
  "quality": "balanced",
  "endpoints": {
    "start": {"mode": "body_fixed", "rigid_node_id": "实际左手柄node_id"},
    "end": {"mode": "body_fixed", "rigid_node_id": "实际右手柄node_id"}
  }
}
```

手柄作为独立 CAD 实体，使用其原生材料密度/刚体配置。省略端部时为 free/free；body_fixed 只表示线端连接真实手柄，不自动决定手柄的 static/dynamic/kinematic 模式，更不表示被握住。根据任务核对已有配置，或在首次 raw 包的 --base-config 中通过 parts[handle].rigid_body.mode 选择 kinematic 来表达需指定运动的手柄；实际动作另行施加。线端直接固定世界则在 request.endpoints[side].mode 选择 world_fixed，不能把 world_fixed 写成刚体模式。已有物理/FEM对象的转换保留原来的显式转换开关。

## 几何、类别和取值顺序

`configure-cable`优先读取所选occurrence的真实BREP、原生mm和世界变换。完整实心直圆柱要求一个圆柱面、两个平面盖及体积一致，直接得到轴线、材料长度和外径，不按包名或显示名猜尺寸。其他已支持平面路径由Agent提供CAD建模参数生成的world-SI polyline：`geometry={centerline_m,diameter_m,source}`，可加`free_start_m/free_end_m`。弧长由程序逐段计算，不能伪填；同一真实直圆柱的冲突几何拒绝。通用BREP中轴反求、整条中心线包含性证明和空间初态未实现。直线自然态仍会使弯曲初态回弹。

自动入口只接受 `stranded_wire` 或 `pvc_jump_rope`，必须显式传入 category；缺类别和未知类别均拒绝，没有未知描述默认电线的分支。Agent 负责确认预设适用，未知对象若满足圆杆链合同则使用下面完整声明。`preset_version` 可要求当前 `2026.10.1`；读取已保存资产不查当前预设。

优先顺序为本次提交的 properties、匹配 evidence、预设补缺。estimated 与 explicit 都是调用者明确提交的有效决定，source 不再作为用预设覆盖调用者数值的排序开关；同名 properties 胜过 evidence，调用者须在提交前保留用户要求并说明资料取舍。evidence 仍仅接受真实 reference/calibrated；reference 要 detail/citation/conditions。兼容 classification 字段只核对其与 source.kind 一致，不决定数值权威。

新输入必须有逐字段、组或根 source，逐值覆盖组，组覆盖根。无来源裸值和缺 source 的简写 wrapper 拒绝，错误指出字段；不自动标用户输入。估计、几何、N/目标段长、solver 和预算都遵守该规则。程序补缺参数标 default，不能继承 Agent 根来源冒充估计或用户值。下面示例用根 estimated，用户指定的线密度另行覆写来源；数字只说明格式：

```json
{
  "description":"适用普通多股软电线；依据任务提交初始估计",
  "category":"stranded_wire",
  "source":{"kind":"estimated","detail":"针对当前构造的初始估计；需另述假设和适用条件"},
  "properties":{
    "linear_density":{"value":0.018,"unit":"kg/m","source":{"kind":"explicit","detail":"用户明确给出线质量"}},
    "joint_damping":0,
    "restitution":0
  }
}
```

参数根 source 只表示声明者给出的依据，插件不判定资料真实性。Agent 不能为绕过规则把估计改标 explicit/reference。确定性换算和决策保存接口见 [Agent 决策与来源](agent-decisions.zh-CN.md)。

支持的属性名和单位见 `cable_inference.PROPERTIES`：线密度或整线等效密度、EI/GJ、每关节阻尼、刚体线/角阻尼、摩擦/恢复、几何弯曲限位、重力及碰撞开关/偏置。`equivalent_density`按实际外圆面积换算λ，同一提交层同时给λ和ρ时拒绝；properties 的λ/ρ决定优先于 evidence 的另一种表示，避免重复质量权威。用户0/false不被默认覆盖。抗拉当前是D6平移锁定的不可伸长近似，**有限EA、断裂、内芯滑移和连续分布阻尼没有实现**；输入`tensile_rigidity/youngs_modulus`等未知字段会拒绝，不写假字段。

description仅保存任务文字，不做硬度关键词匹配。Agent可显式选择feel=normal/stiffer/softer，省略为normal；fresh预设分别使用EI/GJ倍率1/2/0.5，不改λ、质量或阻尼，倍率只是未标定工程档位。fresh 请求的重复“更硬”仍选择同一档位，不逐次翻倍；提交的 EI/GJ 优先于该补缺。已保存对象重配置保留所有实际参数和 N，只改定性标签不重新推断；Agent 若决定增硬，应提交有来源的新 EI/GJ，回读其实际值。

## 不匹配预设的自定义细长体

现有公开 `set-rigid-chain` 不经过类别预设和上述优先级。它接受 [完整声明合同](rigid-joint-chains.md) 中所有 group、endpoints 与 source；结构可参考 [格式示例](../examples/rigid_chain/chain.json)，不照搬其材料、16段、480Hz或边界。此入口不能直接接收自动请求的 description/category/feel/quality/properties/evidence 或 discretization.mode。

顶层 `source:{kind:"estimated",detail:"当前对象的构造、参数及选段依据和适用条件"}` 可让声明中的简写值继承估计来源；用户明确给出或有匹配资料的参数分别使用 `{value,unit,source}`。此入口的 wrapper 没有 classification。明确的用户值、0/false 和合法性要求仍保留，不能为了通过而伪造来源。

此入口只接受显式 `discretization.free_segments`。Agent 可根据尺寸、初曲率、预期弯曲/接触细节与计算预算说明目标段长 h 的依据，计算 `N=max(2,ceil(Lfree/h))` 后提交；这是调用者选段，不是已实现的通用自动选段或误差自适应。材料坐标和中心线须符合合同，任意 BREP 中心线包含关系仍未自动证明。

```powershell
# $Declaration 是依据当前对象准备的完整声明 JSON，不是 configure-cable request。
& $PhysicsPython -I -B -m sca_physics inspect $RawPackage
& $PhysicsPython -I -B -m sca_physics set-rigid-chain $RawPackage `
  --target $ExactCableNodeId --chain-id custom --config $Declaration --output $NewFinalPackage
& $PhysicsPython -I -B -m sca_physics validate $NewFinalPackage
# 每条命令启动新进程；独立导出不再读取 $Declaration。
& $UsdPython -I -B -m sca_usd_export export $NewFinalPackage $NewUsda
& $UsdPython -I -B -m sca_usd_export validate $NewUsda
```

输出变量均为新路径，真实 node_id 由 inspect 获取；首次 raw 包可另传 --base-config。需要替换原有刚体/FEM 时必须满足原生关系约束并使用对应显式转换开关。--reconfigure 只属于 configure-cable，不适用于此入口。

圆截面、平面初态、直线自然态和不可伸长近似仍是硬边界；有限 EA、空间初态、无应力曲线自然态、扁带、分叉、真实多芯内部结构及连续分布阻尼未实现。需要这些能力时说明缺口，不能改标签或补无效字段。已有 FEM 也有其真实 CAD、网格、端部和后端要求，不能当作任意柔体的默认替代。

当前导出隐藏原 CAD 语义 occurrence，动态显示、碰撞及惯量采用 Capsule 代理，显示色为固定深灰。质量按材料弧长分配，胶囊高度按端点弦长，端帽伸出端点；CAD 语义/材料保留不等于动态外形或颜色原样保留。相邻过滤必需；材料邻域过滤按材料坐标处理局部重叠，保留远弧长折回接触，端部过滤只作用于声明涉及的连接。插孔等普通刚体使用 convexHull 可能封孔，须独立检查实际碰撞表示和接触行为。

## 小型预设与依据

|类别|参考外径/线质量|整线EI/GJ工程初值（Nm²）|每关节c工程初值（Nms/rad）|
|---|---|---|---|
|stranded_wire|2.6mm / 0.015kg/m|5e-4 / 1.5e-4|1e-7|
|pvc_jump_rope|5mm / 0.021985kg/m|3e-4 / 2e-4|5e-7|

线质量按同类外径比²缩放，EI/GJ按比⁴缩放。这是假定构造相似的整线工程外推，不是材料名称自动确定属性。电线不使用纯铜×整根外径截面惯性矩。PVC跳绳参照有内绳芯，也使用整绳等效值，不视为均质实心PVC。

线质量/尺寸的资料参照为[LAPP H05V-K](https://products.lappgroup.com/online-catalogue/power-and-control-cables/control-cabinet-single-cores/various-applications/h05v-k.html)的1mm²规格，以及[Elite PVC替换绳](https://elitejumps.co/collections/jump-rope-teams/products/pvc-replacement-cords)的5mm绳长/质量；后者小端扣可能计入。它们不能证明所描述物体就是该SKU，也没有给本预设EI/GJ或阻尼。绞线[整线弯曲模型论文](https://doi.org/10.1016/j.ijmecsci.2019.105355)仅作构造和量级参照，未标定本预设。刚度、阻尼、接触和“更硬”倍率均明确标工程估计。初始外径适用区间wire2–6mm、rope4–6mm，超出仍可生成但写明外推警告。

## 确定性选段与预算

以下仅描述两类预设的当前实现，规则版本 `uniform-cable-2`。设实际自由弧长 Lf、外径 d、解析后的 EI、λ与实际 gravity_magnitude=g，g>0时特征长度 `ell_g=(EI/(λ*g))^(1/3)`；g=0时省略此项，不保存Infinity。它只定义分辨率特征，不预先规定重力下垂量。balanced候选段长取以下最小值：

- wire：8d、0.5ell_g、Lf/20；rope：12d、0.8ell_g、Lf/20。
- 有初态曲率时再限为对应15°转角的弦长和0.25d弓高误差的弦长。曲率来自实际输入polyline的三点外接圆，稀疏采样遗漏仍是限制。

最后 `N=max(2,ceil(Lf/h))`，实际自由段长 Lf/N；两侧非零非自由端区间各加一个材料刚体，独立手柄另算 actor。preview/fine 按公开 QUALITY 表改变分辨率、初态转角/弓高和求解起点；auto 的最低段数分别为12/20/32（preview/balanced/fine），显式 N 与目标段长走另行分支。这些固定常数是初始工程规则，不是标准、普适最优或收敛证书。算法未使用实际载荷、动作、接触结果、步频/迭代收敛或运行误差，也不会在仿真中自适应加段。20/29/20/47仅是既有输入的回归结果，不能要求新物体凑出这些段数。

balanced初始solver：wire1200Hz、rope960Hz，TGS/P64/V4；preview900/720Hz P32/V2，fine2400/1920Hz P96/V4。高刚度、接触或用途仍需检查。16384/P255/V0仅保留为上一阶段精细对照；480Hz有已记录的失准证据，本版不宣称它是通用可靠设置。

新版没有512的普适后端硬限。旧1.4/1.5合同仍保持2..512；Schema1.6历史预算合同和新1.7预算声明允许更大N，先做资源检查。默认预算是场景256刚体/256关节/256碰撞体、4096过滤对、32768潜在接触对、80,000,000链求解工作单位/秒；可在request.resource_budget部分覆盖；新1.7六项保存value/unit=count/source包装，提交覆盖须有自身、组或根来源。六项字段为 `max_bodies/max_joints/max_colliders/max_filtered_pairs/max_contact_pairs/max_solver_work_per_second`。工作量估计为Σ链段数×Hz×(P+V)，不包括全部普通对象/接触成本，不是计时保证。physics先用CAD部件计数保守检查，USD在真实归并后对整个场景复核，多预算取最严格者；有预算的新链不能借混合legacy链绕过总量限制。

超预算明确报错，不裁剪N、不暗降质量、不改材料；调用者可明确提高预算、减少场景负担或选择preview。禁用自碰会产生全对过滤，二次规模在分配前按组合数检查；启用自碰时相邻/材料邻域过滤采用输出敏感枚举。预算是计算保护值，不能从通过预算推断后端性能或工程精度。

三种输入互斥：`discretization={mode:"explicit",free_segments:N}`、`{mode:"target_length",target_segment_length_m:h}`、`{mode:"auto"}`。显式 N 或 h 须有来源；目标段长和自动模式的最终 N 以 derived 保存具体长度/目标值及公式。旧 set-rigid-chain 接受完整显式声明。旧包重开/导出不改 N；对已有目标 configure-cable 必须显式 --reconfigure。重配置以已保存的所有实际 wrapper（含 default/estimated）、N、solver、预算继续，不解析旧 raw 请求重造来源。新同名值才替换；已有explicit用户参数只能用新的explicit用户来源修改，不能被Agent估计或程序默认覆盖；新明确选择 auto/target_length 才重新选段。只说“比较硬”不重新按预设覆盖旧 EI/GJ，需提交有来源的新数值。

没有resolution的旧手工包仅在结构可无损保留时接受自动重配置：中心线/材料站点/自由区、截面和端半径、三个过滤开关以及场景solver类型/GPU/broadphase若会被新自动入口改变，则明确报错，不改原包。继续使用已保存资产，或通过原`set-rigid-chain`完整声明编辑；不把这种受限转换说成任意旧包都可自动重配置。兼容结构的旧包保留全部来源的步频、迭代数及CCD/端部应用开关，0/false和来源不丢失；新请求可通过`solver`和已有body属性`properties.enable_speculative_ccd/apply_to_endpoints`明确覆盖。

## 保存与按任务验证

configure-cable 生成的描述配置保存完整生效参数及 N、CAD绑定，再加 resource_budget 和 resolution：原描述、解析请求、类别/预设版本、来源分类、实际几何、选段规则/候选依据/实际段长、solver建议、预算结果、验证范围与限制。两个 SHA 快照检测生效值和推断记录意外不一致，不是数字签名。新版读取仅验证保存结果，不查询现行预设、不随机推断、不隐式重分段。新手工 set-rigid-chain 写Schema1.7，也可合法保存无 resolution/budget 的完整声明，不能将这些可选记录缺失判为损坏。新 Schema 不是 SCA 主格式变更。

描述配置的 resolution.validation 明确配置已校验、native不是planner可以断言的结果、物理精度未建立。USD报告继续区分生成/静态重开与仿真证据。描述配置还保存float32几何舍入建议，默认USD导出可消费，显式导出配置优先；这不是放宽力学门槛。

验证围绕任务目标确定观测内容、时长、计算预算及终止条件，说明每个判据的依据、适用范围和触发动作。物理参数（λ/EI/GJ、阻尼、接触等）描述所选近似；求解设置（Hz、TGS、迭代等）控制数值执行；resource_budget 保护计算资源；测试阈值决定特定检查如何报告或停止。四类数值不能互相替代，资源或输入校验通过不是精度证明。

| 验证层级 | 可作出的结论与所需证据 |
|---|---|
| 初始化检查 | 核对真实后端注册、对象身份、质量/惯量回读和有限状态；报告检查时长及停止原因。 |
| 行为验证 | 在指定载荷、动作、连接和接触条件下观测所需行为；没有施加目标动作就不宣称动作验证通过。 |
| 精度验证 | 对目标量采用适当的步长/迭代/分段收敛与理论或实物参照；运行结束或形状看似合理不充分。 |

配套 USD payload 的 `scripts/cable_runtime_smoke.py` 默认请求0.25秒，单次默认预算0.5秒/2048步，可由现有 --max-duration/--max-steps 显式覆盖，--duration/--steps 互斥；没有全局“两次”计数器。代码仍把两次/每次0.5秒写入 `resolution.solver.finite_trial_budget`，这是遗留建议记录，不是用户任务上限或物理判据；独立导出不改写该字段，文档调整也未改变代码。

smoke 不施加额外指定载荷或动作；延长它不能自动升级为行为或精度验收。脚本仍硬编码 joint gap 0.5mm、线速度10m/s、四元数范数误差及链段质量/惯量相对误差等守卫，没有通过 CLI 修改这些数值的接口。超守卫会由检查器抛错停测，记录失败，具体保存顺序和结果以实际输出为准。依据2026-10-23阈值追溯，10m/s来自助手的工程停测线，没有查明它是跳绳物理速度上界的依据；只凭越线不能认定仿真错误、失稳或发布阻塞。其他沿用容差也不自动成为通用物理标准。检查 summary.passed、error、completed_steps 和 metrics；进程 exit0 不能替代结果检查。

运行记录区分初始化、行为与精度的通过、失败、未运行，保留提前停止及原始 false，不事后改材料、动作或放宽阈值掩盖结果。缺 Isaac 时可完成配置/导出，但 native 标未运行；是否已满足交付用途取决于用户目标和实际证据。既有严格瞬时静态及动态分段等价的限制仍保留，详见 [验证记录](validation.zh-CN.md)；它们既不因文档修正自动通过，也不替代对当前任务的具体判断。

## 本版修正与仍有的边界

0.1.7rc2已修正未知描述兜底、preset覆盖提交估计、无来源裸值冒充用户及重配置重新推断问题。新 Schema1.7 引入严格来源和可重算 derived 记录；旧1.0–1.6保留，不用新事实改写历史来源。需求、表示、估计依据和分段理由可通过 decision 及 bindings 随最终包保存。

仍没有类别中立自动 CLI、载荷/动作或误差驱动自适应。自定义对象可用完整声明与公开 circle_rod/derived helper；Agent需解释选段和边界。`resolution.solver.finite_trial_budget`仍是历史建议字段，未改成运行上限。

USD 运行守卫、结果分类与退出状态的待办见配套 exporter 的 `docs/automatic-cables.zh-CN.md`。有限伸长、非平面空间初态、无应力曲线自然态、连续阻尼和动态原 CAD 外观绑定均需新增实现，不能靠文档、无效字段或更换类别标签获得。
