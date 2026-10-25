---
name: sca-physics
description: 在 SimpleCADAPI 建模和 capture 后，为 .scadpkg 补充并校验有来源的物理配置，供配套 sca-usd-export 独立消费。按任务选择刚体、受限 FEM 或圆截面刚体关节链；适用对象可选电线/跳绳预设自动选段，其他受支持细长体可提交完整显式声明。CAD 建模回到主技能，保留原生材料与连接。
---

# 产品包物理配置（0.1.8rc1 独立候选）

实测配对仅为 physics **0.1.8rc1** + USD **0.1.8rc2**；Windows x86-64、Python3.12.15、SCA SDK2.2.5、OpenUSD26.8、OCP7.9.3.1。physics直接必需依赖仅SDK，不导入USD；导出器读取物理数据时也直接导入physics合同/几何模块，需其可选physics extra的精确版本。无嵌入物理配置可只用/升级USD；已有physics0.1.8rc1无需同号升级，更新USD后重新provision。较旧物理用户先准备匹配导出器及peer，再切换physics写入入口，不能只降低schema标签。

旧包实测仅含2026-10-19 physics0.1.0/schema1.0与2026-10-20 physics0.1.3rc1/schema1.1所选文件，完整输入哈希、producer证据及路径/内存API见实际payload的`docs/release-candidate.zh-CN.md`。**旧无来源裸参数原样不兼容；按要求补充来源信息后，所测试案例通过。**字段/组/声明根source须真实，reference含detail/citation/conditions；随包`examples/pendulum/physics-input.json`为已运行迁移例子，其false的软件试验来源不得套作真实产品依据。

本机Windows未开启长路径时须选短状态/runtime根；已测`personal-workspace/results/arp-20261025-162555/s`与`p`，其下`a`为home、`s`为skills。深路径的Jedi安装失败未通用修复。两项外部FEM检查、Isaac／PhysX行为、其他环境及全部历史版本组合未验证；安装/保存/导出成功不能宣称原生行为或精度全面通过。SDK/运行依赖、构建test extra与外部仿真环境须区分。

先使用主 SimpleCADAPI 技能完成建模、原生材料密度、连接器、约束、求解和 capture。产品包格式遵循该技能 `references/scadpkg-format.md`，规范 schema 随 SCA 安装于 `simplecadapi/contracts/`。本插件无需 interface 标签，长度仍为毫米；物理输入采用明确 SI 单位。

1. 首次运行前，对调用者明确选择的 add-on home/skills-dir 执行 `sca addon check --home <home> --skills-dir <skills> sca-physics`，用同样显式路径的 `addon use` 确认实际 payload/runtime 和0.1.8rc1版本，不切换全局 stable。检查真实runtime_check.passed；管理命令返回0不等于probe通过。缺运行环境时使用同一home的 `addon use ... sca-physics provision`；不把依赖装入建模环境。描述文件probe是 `check`（通过command_prefix在独立Python中运行）。
2. 调用 `inspect 原始包` 获取可验证的 node_id、definition_id、joint_id。用 `template 原始包 --output 新输入.json` 获取原 1.0 完整格式，或按 [物理字段与参数选择](references/physics-format.md) 生成稀疏输入。需要可选机械字段时使用 `template 原始包 --include-mechanical --output 新输入.json`；其新增字段均表示交给引擎，不含数值，刚体模式省略。不要用显示名绑定。模板值如被改变，应同步修改来源。
3. 根据物体构造、尺寸、用途、载荷、运动和接触需求判断现有表示是否适用；保留用户明确数值并检查单位。缺参时优先寻找匹配资料，或形成可解释的工程估计，记录假设、单位、来源和适用条件。可用可逆假设推进；影响模型适用性或关键边界的歧义需要澄清。细长体按下节选择预设或完整声明，不强行归类。旧 enrich 的 demo-v1 是既有字段的兼容默认，必须标 default，不是未知实物的材料推断。估计值标 estimated，不能伪称用户输入或实测。不改写原生 CAD 密度或连接；所选 FEM 实例的仿真密度由其柔体材料声明权威提供，不进入原刚体质量处理。
4. 用 `enrich 原始包 --config 输入.json --output 新包.scadpkg` 补齐原 demo-v1 字段、严格校验并持久化。新机械字段省略时不补值；未指定 schema 时，含新关节/Articulation字段写入1.8，否则保持1.7；旧 template 仍输出显式1.0/1.1，显式旧schema不能混入后来字段。默认输出新文件；输入 JSON 只是可复现输入。已有包的部分更新用 `update 已有包 --config 有来源的patch.json --output 新包`（公开Python `update_config`/`update_package`）；仅改指定字段，wrapper原子替换且新值不能继承旧来源，未改线缆/显式值保留，自动schema升级记录在报告。结构删除或整体替换可用 `enrich 已有包 --config 明确的完整配置 --output 新包`；无配置重复 enrich 仍拒绝。修改同一 CAD 柔体的材料时优先使用下面的 `set-deformable --material`，无需重新建模或从原 capture 重做。
5. `inspect 新包`、`validate 新包`，核实根定义 metadata.sca_physics 中实际值/单位/来源。需要审计时保存独立期望快照并 `validate 新包 --expect 快照.json`。检查补包报告的几何、材料、连接、历史及 scene 保留结果。
6. 用配套 0.1.8rc2 sca-usd-export 技能导出最终包，其物理集成需可选physics依赖sca-physics==0.1.8rc1。导出时优先读取包内配置；无需输入 JSON。检查 USD 重开验证报告、刚体归并与冲突诊断，以及任何未支持项。区分包内保存/读取、USD 属性检查、PhysX 有效初始化和行为验证。纯几何导出无需本插件；使用Schema1.8前先准备匹配导出器，不能只降低schema标签后导出。

旧刚体/接触的可选机械参数可写 `{mode:"engine_default",unit:"...",source:{kind:"explicit",detail:"选择引擎默认的原因"}}`，不得同时带 value，也不得用 null。它明确要求不写对应 USD opinion；引擎哨兵值和运行时解析值不是产品里已经固化的实测参数。静态对象上的该类请求可报告不适用；显式刚体重力/阻尼用于静态对象时由导出拒绝。`rigid_body.mode` 只允许显式 static/dynamic/kinematic 或省略，不能用 engine_default，也不能用它绕过原生 ground/root/frozen 约束。固定连接归并后的冲突须解决后再导出。FEM 材料与 body 字段不接受此 engine_default wrapper；省略可选字段即可不写对应 opinion。

新增刚体阻尼单位为 `1/s`，与关节阻尼的 `N*m*s/rad` / `N*s/m` 不同。碰撞 contact_offset/rest_offset 单位为 m：contact_offset 必须正；rest_offset 可以为负，正值必须配显式且更大的 contact_offset。不要把引擎 -inf 哨兵复制成参数，有限浮点须可写成 USD float32。材料摩擦/恢复组合模式仅限 average/min/multiply/max，不从材料名称猜测组合策略。

用户明确输入优先，显式 `0`、`false` 必须保留，不能被材料预设或默认策略覆盖；非法值或单位冲突应指出具体字段，不静默裁剪。只有材料或用途描述时，仅推断有依据且适用的参数，并在 source 中记录依据、假设和适用条件；材料名不能唯一确定刚体阻尼、接触偏移或组合方式。推断值是可修改的仿真初始估计，不是测量结果。缺少依据时省略这些新字段，或明确记录 engine_default，不能强行填满八项。旧 demo-v1 字段的既有默认策略不变。

命令实际由独立环境 `python -I -B -m sca_physics` 调用；Windows 经 SCA 命令运行含空格/特殊符号参数时，用 payload 的 `scripts/use.ps1` 编码参数数组。详细启动见 payload README，技能安装目录不等于代码目录。

`metadata["sca_physics"]` 是本插件命名空间，不是原生 Material/Constraint/编辑器字段，不会自动加入建模历史回放。重新建模/重新 capture 后必须重做补充。设置 upAxis 是模型级方向声明与重力选择，不旋转几何。非零关节阻尼由下游零刚度、零目标速度 force Drive 提供被动耗散，不设置主动运动目标，也不以刚体角阻尼替代。

Schema1.8 的 joints 可选字段为 motion、lower_limit、upper_limit、max_velocity、friction、drive；drive完整包含 mode(off/position/velocity)、type(force)、target_position、target_velocity、stiffness、damping、max_force。全都保存 value/unit/source，不接受engine_default。旋转用rad、rad/s、N*m/rad、N*m*s/rad、N*m；移动用m、m/s、N/m、N*s/m、N。position要求正刚度，velocity要求零刚度且正阻尼；limited必须lower<upper且position目标在限内。assembly.articulation完整声明enabled/fixed_base布尔wrapper与稳定root_node_id；保存身份合法不等于Articulation拓扑有效。原生父子frames/轴/零位保持，后端需要有效Articulation的字段由导出检查。

articulation还可显式声明self_collisions布尔wrapper，省略时导出器明确采用并报告true，保存不注入默认。Schema1.8可选顶层couplings[id]{representation:"mimic",reference_joint_id,follower_joint_id,gearing(m/rad wrapper),offset(m wrapper),source}，方程q_follower+gearing*q_reference+offset=0。仅原生有限revolute→有限prismatic，同一有效enabled Articulation，每follower唯一owner，gearing有限非零，offset有限且范围可行；follower不能有主动drive，passive damping必须0。初态与实际树由导出器检查。理想近似不模拟齿隙/弹性/齿面啮合，必须以模型可靠来源给参数，不能外观猜测。m场景USD gearing=SI gearing*π/180；独立真实native运行验证后才声明传动成立。

主动驱动与旧被动阻尼共享force通道：Dtotal=Dp+Da，有效速度目标=Da/Dtotal*vt（总阻尼0时0），K保持；off只保留旧passive。max_force限制组合后的总驱动力，不能声明为真实额定电机参数或实测力矩。运行脚本只更新最终包正式导出的已有drive目标，不临时补建API/增益。局部坐标、角增益换算、限位、来源与限制详见实际payload的 `docs/joint-physics.zh-CN.md` 和本技能 [字段参考](references/physics-format.md)。

## 按任务选择细长体流程

Agent 负责理解描述、判断模型和资料的适用性，程序负责确定性计算、校验、保存与导出。先用 `inspect` 确认真实 occurrence 和端部实体，再选择路径：

| 对象情况 | 当前可用入口 |
|---|---|
| 与普通多股软电线或 PVC 跳绳预设匹配 | 查看 `cable-presets`，在请求中显式指定 `category`，用 `configure-cable raw.scadpkg --target ID --config request.json --output final.scadpkg`。 |
| 不匹配预设，但圆截面刚体链近似适用 | 用下节 `set-rigid-chain` 提交完整、有来源的声明；无需冒充两个类别之一。 |
| 需要当前模型未实现的行为 | 说明具体缺口；其他已有表示仅在满足其合同后采用，不能默认改用 FEM 或强行生成电线。 |

`configure-cable` 只有 `stranded_wire`、`pvc_jump_rope` 两类，必须显式传入适用 category；缺失或未知类别拒绝，不用名称关键词兜底为电线。完整实心直圆柱可读 BREP 尺寸；其他已支持平面路径需有来源的 world-SI polyline/diameter，没有任意 CAD 中轴反求。

新输入采用 Schema1.7 严格来源：逐值 source 覆盖组 source，组 source 覆盖声明根 source；没有任一来源的裸值或不完整 wrapper 拒绝并指出字段。估计标 estimated，用户确实指定才标 explicit；reference 必须有 detail/citation/conditions。该规则覆盖物性、几何、段数/目标段长、solver 与预算；程序缺省值保留 default，不继承调用者来源冒充显式输入。

提交的合法 properties 优先于 evidence，预设只补缺；针对物体的 estimated λ/EI/GJ 可以生效，0/false 保留。同一层同时给 λ 和等效ρ拒绝；ρ按实际圆外径换算为 derived λ。分类只是来源标签，不再按 preset 高于 estimated 的旧顺序夺取权威。

description仅记录任务，不解析类别或硬度关键词。预设适用且Agent显式选择feel=stiffer/softer时，仅对fresh preset EI/GJ使用固定2/0.5倍率，省略feel为normal；这不是材料推理。已保存对象重配置从所有实际 wrapper 继续，包括 default/estimated、N和solver，仅新的同名输入替换；已有explicit用户参数只能由新的explicit用户来源修改，Agent估计不得覆盖。只改定性标签不会重新推断或翻倍；Agent 若决定改变抗弯，应提交带来源的新 EI/GJ，并回读核实。

公开 `from sca_physics import circle_rod` 可把有来源的圆杆 d、ρ、E、G 确定性换算为 λ/EI/GJ。输出 derived wrapper 随包保存规则、固定公式、实际输入及各自来源；外部序列化后再提交也会重算核验。可选 decision 记录需求、表示、依据、假设和限制，并用 bindings 关联实际参数与材料 ID。具体接口与示例见实际 payload 的 `docs/agent-decisions.zh-CN.md`；不凭公式验证声明材料真实性。

自动选段按自由长度、外径、初曲率、EI/λ 和质量档计算，是初始工程估算，尚不根据实际载荷、动作、接触结果或运行误差自适应优化。显式段数、目标段长、auto 互斥；超预算明确反馈，不静默截断或改材料。自定义声明由 Agent 说明目标段长依据、计算并提交显式 N；当前没有类别中立的自动选段 CLI，历史案例段数不是目标答案。

端部依据实际边界选择：默认 free/free，手柄连接使用真实 body_fixed ID，握持或运动意图另行明确配置。保存后在新进程 `inspect`/`validate`，核对实际值、单位和来源；描述配置另核对 resolution 和最终 N。独立 USD export 仅消费最终包，不再次推断。新决策通过 physics 明确重配置；`--reconfigure` 仅属于 `configure-cable`。

按任务目的确定验证内容、时长和计算预算，并说明终止条件。初始化检查核对真实后端对象、质量/惯量及有限状态；行为验证需要对应载荷、动作、连接与接触观测；精度验证需要相应收敛、理论或实物依据。短 smoke 或延长其时间均不自动证明行为、精度合格。缺后端或证据时标未验证，不能替用户认定近似资产已满足用途。

物理参数、求解设置、资源预算与测试判据分别报告。现有 smoke 的 10 m/s 是硬编码工程停测线，超线会停止并记录失败；尚无其为跳绳物理速度上界的依据，不能仅凭越线判定仿真错误。当前脚本预算、守卫动作和代码待办见 payload `docs/automatic-cables.zh-CN.md`，按需读取；技能目录不等于代码目录。Agent 查资料与本地执行分开，确定性计算、已保存包校验和独立导出不需要在线模型服务。

## 明确中心线的圆截面刚体关节链

支持 metadata schema1.0–1.8。仅刚体链的新写入使用1.7；增加新关节/Articulation/耦合字段时使用1.8，两者都保存严格来源和可复算 derived 记录。旧1.0–1.6只读校验/导出保持原值、来源与段数，不自动升级。旧1.4 physics_hz限1..4096，1.5–1.8为1..16384。旧1.4/1.5分段2..512；1.6–1.8预算声明可允许更多。position iterations1..255、velocity iterations0..255保持；允许保存不代表力学收敛。

本路线不经过 FEM。先创建 CAD/capture，再用 `inspect` 选择真实 part occurrence，然后运行：

```text
python -I -B -m sca_physics set-rigid-chain raw.scadpkg --target 精确node_id --chain-id cable --config 完整声明.json --output final.scadpkg
python -I -B -m sca_physics validate final.scadpkg
```

有额外刚体模式或方向设置时，可对尚无 sca_physics 的 raw 包添加 `--base-config 基础配置.json`，一次保存成最终包。目标原有 rigid_body/FEM 必须分别显式 `--convert-rigid` / `--replace-deformable`。所有未知字段、缺失输入、错单位、过期 CAD 绑定、目标的原生 ground/joint 都要报错，不静默丢约束。

新的完整显式声明保存为 schema1.7；手工入口可无 resolution/budget，独立导出按已保存声明消费。声明位于 `cables[id].representation="rigid_joint_chain"` 和对应 parts.physical_type。此入口由调用者提供世界 SI 中心线、材料弧长、线径、显式分段数量、单位长度质量、EI/GJ、每关节阻尼、碰撞、两端模式和来源；不接受自动入口的 request 或 discretization.mode。顶层 `source:{kind:"estimated",detail:"估计依据及适用条件"}` 可让简写参数继承估计来源，用户给定值和资料值用各自 `{value,unit,source}` 覆写；此入口不接受 classification 字段。完整字段见实际 payload 的 `docs/rigid-joint-chains.md`；`examples/rigid_chain/chain.json` 仅示范格式，不能照搬其材料、16段或480Hz作为其他物体的推荐。当前没有任意 CAD 中心线反求，参数缺省不能用旧实验数字补齐。

当前接受直线或平面曲线初态、圆截面、直线自然参考、per_joint 阻尼和 free/world_fixed/body_fixed 端点。D6 平移锁定是不可伸长近似，有限抗拉刚度未实现。空间初态、弯曲自然态、连续分布阻尼、扁线、分叉、多芯内部结构未实现并拒绝。曲线初态具有相对直线自然态的弹性预载。胶囊同时用于动态显示、碰撞和惯量近似；质量按材料弧长 λΔs，内部刚度按 EI/ell 或 GJ/ell（ell为相邻材料段长均值）生成。改变段数时每关节 c 不表示相同连续体耗散。原 CAD 隐藏作语义/来源保留，当前动态胶囊使用固定深灰色，不能承诺原 CAD 外形和颜色随链运动原样保留。

中心线及导出所需配置随最终包保存，后续 USD 正式 export 只接收 final.scadpkg，不需要原中心线 JSON、V6 脚本或旧 USD。分段、惯量、D6 和端部生成由配套 USD 插件完成，physics 仅声明/校验/保存。不能将参数估计或软件回归说成实物标定，也不能将静态重开说成动力学通过。

胶囊端帽向外延伸，相邻段必须过滤。当分段小于线径附近，显式 collision.filter_material_neighbors=true 可另外过滤材料区间弧长间隙不大于两段半径之和的局部 pair，远弧长折回仍接触。默认 false 保持原 V6 过滤；这不是关闭所有 self collision，也不应作为任意接触问题的通用修复。

已有分段一致性、扭转及严格静态对照的限制保留，详见 payload `docs/validation.zh-CN.md`。描述配置与自动选段不自动获得精度认证。增加 EI/GJ 后某次同条件响应变小，也不足以宣称整线实物标定完成。

## 已有 CAD 线缆实例的后附加 FEM 与材料编辑

使用调用者选定的 **physics 0.1.8rc1 / USD 0.1.8rc2 配套隔离解释器**，不要混用默认 stable 或其他候选。先 `inspect` 获取精确 occurrence `node_id`；共享同一 CAD 定义的实例必须分别选择，显示名与 definition_id 不是选择器。

- 首次调用 `set-deformable 原始或已有包 --target node/装配/线缆 --config 完整声明.json --output 新包.scadpkg`。声明必须绑定真实 CAD/BREP，包含官方从该闭合 CAD 表面生成并冻结的网格、材料、参考形状和两端附件；此接口自身不调用 Isaac cooking，也不凭空生成另一条无 CAD 身份的线缆。
- 后续调用 `set-deformable 已有柔体包 --target 同一node_id --material 材料.json --output 新包.scadpkg`。例如用户明确提供的材料输入 `{"source":{"kind":"explicit","detail":"用户明确给出这三个材料参数"},"youngs_modulus":20000000,"poissons_ratio":0.35,"density":1500}`，单位分别为 Pa、1、kg/m³；Agent 估计则使用带 estimated 来源的完整 `{value,unit,source}`，不能用裸数值冒充用户输入。保留既有 cable_id、目标实例及未变化的官方网格，保存后再导出 USD 并重新加载验证，无需修改插件或建模程序。
- Python 对应 `sca_physics.deformable.upsert_deformable_volume(package, target_node_id, declaration=None, material=...)` 返回完整配置，再交给 `enrich_package(package, config)` 保存。已有 `rigid_body` 块须显式 `convert_rigid=True` / `--convert-rigid` 删除；目标原生接地、固定或 joint 当前明确拒绝，不能静默丢弃关系。
- schema 1.3 的 `geometry_source`、`generation_config.reference_geometry` 与缓存 key 绑定真实 BREP、单位、世界变换、端面法向、网格及观测输入。改变这些输入会拒绝旧缓存，需更新网格及相关节点选择/映射；纯材料修改复用原网格。官方 CAD 网格端部过滤使用明确的 `filter_length`（m），不随分段数隐式变化。
- 当前接口针对两个明确端截面的线缆类零件。材料是工程输入，不是实物标定；有效初始化必须检查原生日志，注册或 USD 重开成功不足以证明行为合格。

完整字段和项目命令从实际安装 `addon_dir` 下的 `docs/cad-deformables.md`、README 及交付说明读取；技能副本目录不是代码安装目录。保留 schema 1.0/1.1 和旧无 CAD 目标的 1.2 声明。

## 原生柔性线缆候选扩展

保留 capture → enrich → 保存后独立回读/validate → export；不调用 0.2.0 authoring 框架。schema 1.2 的 cables 声明由候选配套插件处理，参数与限制见 [线缆说明](references/native-cables.md)。几何网格/原生材料/双向端点附件写入 USD，求解交给 Omni PhysX。仅 GPU dynamics 支持；材质 static_friction 和附件 stiffness/damping 不支持并拒绝输入。用户数值、0/false、SI 单位和来源必须持久化；未知字段报错。USD 静态重开不等于 Isaac 仿真成功。

当前原生 FEM 导出代码对该表示写入 physxScene:timeStepsPerSecond=480（uint，schema fallback=60）；这是实现策略，来源和适用边界见 [线缆说明](references/native-cables.md)，不是任意物体的推荐频率，也不是 Agent 已可自由调节的参数。未完成通用时步收敛标定。无该表示的旧资产不由此策略写入步频；刚体链使用其自身保存设置。

可选 `deformable.enable_speculative_ccd` 为严格布尔，映射本机 PhysxBaseDeformableBodyAPI 的 `physxDeformableBody:enableSpeculativeCCD`。原生后端根据速度动态调整 contact margin，是否启用依据实际接触需求判断。它不是 rigid-body CCD，也不实现自定义求解器。显式 false 原样保存；省略不补值、不写 USD opinion，保留原生 false 默认。选择及依据应保存在参数 source 中。

可选 `collision.attachment_filtering` 是 token 参数 wrapper，仅接受 `whole_body` 或 `endpoint_elements`（unit=token，保留 source）。省略不补入包，沿用既有整线与两个连接刚体组 pair-filter 语义，报告注明兼容来源；显式 whole_body 同义。endpoint_elements 使用原生 OmniPhysicsElementCollisionFilter，仅过滤各自端盖和首个轴向区间的表面三角形，对该端真实刚体组的每个 collider 分别建立过滤器，其余线段仍与插头碰撞。固定生成策略为一个 span，要求 axial_segments≥3，保证中部存在未过滤区域；这不是可变材料/约束参数。报告列出实际 surfaceFaceVertexIndices 行 ID、span 长度和所有 collider 路径；新模式禁止整线 FilteredPairs 残留，验证器按拓扑重新选取并核对 uint[] group counts/indices 与关系。volume–rigid 元素过滤受 107.3 支持，旧 whole-body 选择不是后端能力限制。该功能的实际接触效果仍须单独运行验证。


## 保留的弹性阻尼单位合同

`material.elasticity_damping` 的单位为 `1/s`，对应本机 107.3
`PhysxDeformableMaterialAPI.physxDeformableMaterial:elasticityDamping`。
依据：[107.3 原生 schema 文档](https://docs.omniverse.nvidia.com/kit/docs/omni_physics/107.3/dev_guide/deformables_beta/physx_deformable_schema.html#physxdeformablematerialapi)。
rc1 将该字段标作 `1` 是单位合同错误。rc2 对显式 `unit:"1"` 报错，
不会静默换算、接收错误标注或改写原包。需要调用者在确认原数值含义后
另存 `unit:"1/s"` 的新配置，并按原 enrich → 独立回读 → export 流程生成新资产。
有继承来源的未带单位标量简写仍按该字段既定 SI 单位解释；无来源拒绝，显式 `0` 保留。
该单位合同不对原数值作比例换算；USD 的数值映射不变。
schema 1.0/1.1 与旧流程保持兼容。这是独立合同修正，**不代表已解决拉伸、
传力、反转或动作目标失败**。
