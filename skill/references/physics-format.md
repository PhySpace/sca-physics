# sca_physics 基础字段与 Schema1.7/1.8 来源

最终根定义 metadata 的 `sca_physics` 是封闭对象。基础1.0/1.1字段见下表；当前新配置默认写入1.7，仍保留原 schema1.0–1.6的读取/独立导出，不升级旧来源或重选旧段数。原 `template` 保留显式1.0，`--include-mechanical` 保留显式1.1；其完整来源应随值调整。

含新增关节/Articulation字段的输入自动选择1.8，显式旧schema拒绝这些字段。`joints[id]` 可选 motion(token free/limited)、lower_limit/upper_limit(rad或m)、max_velocity(rad/s或m/s)、friction(1)，以及完整 drive{mode,type,target_position,target_velocity,stiffness,damping,max_force}。mode为off/position/velocity，type仅force。位置/速度分别用rad与rad/s或m与m/s；增益/阻尼分别为N*m/rad与N*m*s/rad或N/m与N*s/m，最大输出为N*m或N。所有保存参数均value/unit/source。position K>0，velocity K=0且D>0；limited两限完整且lower<upper，position目标限内。可选 assembly.articulation{enabled布尔wrapper,root_node_id稳定引用,fixed_base布尔wrapper}由导出进一步核对拓扑。

新增字段省略保持旧导出；drive=off只关闭主动项。被动Dp与主动Da在单个force通道合并为Dtotal=Dp+Da、有效目标速度Da/Dtotal*vt（总阻尼0时0），max_force限制组合总力。SI角增益和角阻尼映射到m/kg USD时都乘π/180，角目标/速度乘180/π。max_velocity/friction需要有效Articulation；不能用接触摩擦、刚体角阻尼代替关节摩擦/阻尼。

articulation可加self_collisions布尔wrapper（省略时包不注入值，导出明确默认true以保留实际自接触）。可选顶层couplings[id]为{representation:"mimic",reference_joint_id,follower_joint_id,gearing:m/rad wrapper,offset:m wrapper,source}，约束q_follower+gearing*q_reference+offset=0。仅原生有限旋转副→有限移动副且同一有效Articulation，gearing有符号有限非零、offset有限，限位交集须可行；每follower唯一owner，drive省略/off且passive damping=0。初始原生求解姿态和树成员由导出检查。m场景底层USD gearing=SI gearing*π/180。此理想传动不模拟齿隙、弹性、效率或齿面接触。

公开 `update 包 --config patch.json --output 新包` 与Python `update_config`/`update_package` 对已有合法快照部分合并；wrapper原子替换且新值不沿用旧来源，列表整体替换，0/false保留，禁止null删除。未修改的历史线缆声明和所有已有参数保留。新能力可自动升级schema并记录；显式旧schema不自动越过。详细示例、完整范围与能力限制见实际payload `docs/joint-physics.zh-CN.md`。

每个保存参数包含 `{value,unit,source}`。source.kind 为 explicit（用户确实给定）、reference（有匹配资料）、estimated（工程估计）、default（版本化程序缺省）；1.7另有 derived（受支持的确定性计算）。reference 的 detail、citation、conditions 均必填。derived 包含固定规则/公式和完整有来源输入，读取时重算。详见实际 payload 的 `docs/agent-decisions.zh-CN.md`。

新输入可省略原 demo-v1 必备字段，由真实 default 补齐；后加的可选机械字段不补默认。提交的数值、布尔、字符串或数组必须有逐值 source，或继承最近组/part/声明根 source；无来源拒绝具体字段，不自动标 explicit。对象可省略正确默认单位，不能指定错单位。null 不等于缺失，0/false保留；未知字段、非有限数值、失效引用、重复碰撞对报错。持久化验证要求完整字段，不能补默认掩盖损坏。

| 路径 | 单位 | demo-v1 | 合法范围/绑定 |
|---|---|---|---|
| scene.up_axis | axis | +Z | +Y 或 +Z；不旋转几何 |
| parts[node_id].definition_id | 标识 | 从包核实 | node_id 必须是零件实例 |
| parts[node_id].contact.static_friction | 1 | 0.5 | 有限非负 |
| parts[node_id].contact.dynamic_friction | 1 | 0.4 | 有限非负 |
| parts[node_id].contact.restitution | 1 | 0.1 | [0,1] |
| parts[node_id].collision.enabled | boolean | true | 布尔 |
| parts[node_id].collision.approximation_dynamic | token | convexHull | 支持的 USD 碰撞近似 |
| parts[node_id].collision.approximation_static | token | none | none 表示网格碰撞 |
| joints[joint_id].joint_type | 类型 | 从包核实 | 不可更改原生关系 |
| joints[joint_id].damping | N*m*s/rad 或 N*s/m | 0 | revolute / prismatic；有限非负 |
| joints[joint_id].collision_enabled | boolean | false | 两端关节碰撞开关 |
| assembly.collision_exclusions | 配对列表 | [] | [{a:零件node_id,b:另一零件node_id,source:来源}] |

支持近似 token：none、convexHull、convexDecomposition、boundingCube、boundingSphere。动态无凸近似网格可能在 PhysX 不受支持，下游必须报告或报错，不能悄悄换值。其他关节只有 damping=0 / unit=unsupported 可保存；非零阻尼报未支持。

参考来源 kind=reference 时 citation 与 conditions 两者必填且非空；estimated 的 detail 应包含估计依据。演示默认不是真实材料数据。比如用户明确旋转阻尼为 `0.0008 N*m*s/rad`，应写该数值、单位和 explicit 来源，而不能写“很小阻尼”。

稀疏输入实例见 `examples/pendulum/physics-input.json`。先 inspect 获取当前包真实 ID，不能把示例 ID 用到其他包。补充后报告含完整解析结果，可复制其 sca_physics 字段为独立期望快照。

USD m/kg 场景 angular Drive damping 单位为 kg*m²/(s*degree)，因此 SI N*m*s/rad 系数乘 π/180；linear damping N*s/m 对应 kg/s，值不变。force Drive 的 stiffness=0、targetVelocity=0 给出 τ=-cω 或 F=-cv。它只抵抗相对运动；targetPosition 在零刚度下无作用。官方依据与实际 Isaac 比较结果见验收报告。

## 1.1 可选机械参数

下列字段均绑定 `parts[node_id]` 的实际零件实例，不改原生几何、密度或连接。只有指定的字段才保存；没有填写的同类字段也不补全。显式参数仍用 `{value,unit,source}`；稀疏输入只在有组/声明继承来源时允许裸值，解析后保存完整包装。`source` 规则与原字段一致，reference 仍需 citation 和 conditions。

| 路径（省略 parts[node_id]） | 单位 | 显式值 | 省略时 |
|---|---|---|---|
| rigid_body.mode | token | static / dynamic / kinematic | 沿用原生 grounding 与连接推断 |
| rigid_body.gravity_enabled | boolean | true / false | 不写该 USD 属性 |
| rigid_body.linear_damping | 1/s | 有限非负，含 0 | 不写该 USD 属性 |
| rigid_body.angular_damping | 1/s | 有限非负，含 0 | 不写该 USD 属性 |
| collision.contact_offset | m | 有限正数 | 不写该 USD 属性 |
| collision.rest_offset | m | 有限数，可以为负 | 不写该 USD 属性 |
| contact.friction_combine_mode | token | average / min / multiply / max | 不写该 USD 属性 |
| contact.restitution_combine_mode | token | average / min / multiply / max | 不写该 USD 属性 |

除 `rigid_body.mode` 外，新字段还支持 `{mode:"engine_default",unit:"对应单位",source:{kind:"explicit",detail:"选择理由"}}`。这是对引擎的明确委托，不含 value、不接受 null，不填入引擎默认数值。导出必须记录未 author，后端哨兵/按形状计算值另记运行证据。静态对象上的重力/阻尼 engine_default 请求允许保存并报告 not_applicable，不写属性；静态对象上的显式重力/阻尼由导出拒绝。`rigid_body.mode` 不能使用该形式，省略它才表示原生推断。

正 rest_offset 必须同时给显式正 contact_offset，且 rest_offset < contact_offset；0/负 rest_offset 可以不指定 contact_offset 或委托引擎。两者显式时，还要在 USD float32 转换后保持严格大小关系。新增浮点拒绝非有限数、float32 溢出和非零数下溢成 0，不把 PhysX 的 -inf 哨兵当产品参数。负 rest_offset 是允许的刚体碰撞设置，不应用旧字段统一非负检查误拒。

本维护版没有引入新的建模保存入口。仍先 capture，再补包；原生 density、质量/质心/惯性计算、关节关系来源与默认场景方向不变。原生 ground/root/frozen 与显式 dynamic/kinematic 的冲突、固定连接归并后的 body 参数冲突由配套导出诊断，不能靠包结构校验掩盖。配置能够保存和官方回读，不等于已有 Isaac 行为证据。

`template 包 --include-mechanical --output 新输入.json` 生成 1.1：七个新标量/布尔/组合字段均为 engine_default，mode 省略。修改具体值时把该字段替换为 value/unit/source 包装，删除 mode 键并记录来源。原 `template` 不带开关时仍输出原 1.0/demo-v1。
