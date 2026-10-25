# 0.1.1 的八项刚体维护范围

目标是本机 Isaac Sim 5、Omni PhysX / PhysxSchema **107.3.18**。本页只记录八项稳定流程扩展，不引入新的物理声明流程或其他 schema 范围。实现继续采用原生 capture → inspect → enrich → inspect/validate → USD export。

## 字段、单位和边界

| 包内字段 | USD 映射和作用对象 | 显式值约束 | 原生 schema 默认 / 适用说明 |
|---|---|---|---|
| `parts.<node_id>.rigid_body.mode` | 实例物理体的 `PhysicsRigidBodyAPI`、`physics:rigidBodyEnabled`、`physics:kinematicEnabled`；static 为静态碰撞体 | `static`、`dynamic`、`kinematic`；grounded 实例不得被改成 dynamic/kinematic | 省略 mode 时保留旧 grounding 与导出策略；mode 不接受 engine_default。dynamic 接受力/重力；kinematic 由应用控制位置，不能据静止或阻尼字段回读声称动力学阻尼生效 |
| `rigid_body.gravity_enabled` | `PhysxRigidBodyAPI` 的 `physxRigidBody:disableGravity`，取布尔反值 | 布尔；显式体参数不适用于 static | `disableGravity=false`；gravity_enabled 的引擎缺省效果为 true。kinematic 可保存/读回，重力不驱动其位置 |
| `rigid_body.linear_damping` | `physxRigidBody:linearDamping`，实例物理体 | 有限且非负；插件输入单位 `1/s` | schema 默认 **0**；schema 文本写 dimensionless，但 PhysX 积分按 `damping * dt` 使用，`1/s` 是基于更新式的量纲解释，不能说 schema 原文如此 |
| `rigid_body.angular_damping` | `physxRigidBody:angularDamping`，实例物理体 | 有限且非负；插件输入单位 `1/s` | schema 默认 **0.05**；同上。刚体角阻尼不同于原生连接的被动 Drive 阻尼 |
| `collision.contact_offset` | `PhysxCollisionAPI` 的 `physxCollision:contactOffset`，实例的实际碰撞形状 | 显式值采用有限、**严格大于 0 m**，并严格大于有效 rest offset | schema 默认 `-inf`，代表引擎按形状尺寸选择。schema 范围文字的包含等号不能当成实际 parser 的合法性证据 |
| `collision.rest_offset` | `physxCollision:restOffset`，实际碰撞形状 | 有限米值，可为负；严格小于有效 contact offset | schema 默认 `-inf`，刚体引擎缺省为 0。schema 范围文字写 `[0,contactOffset]`，与同版 guide/测试的负数支持冲突，须分别保留证据 |
| `contact.friction_combine_mode` | `PhysxMaterialAPI` 的 `physxMaterial:frictionCombineMode`，接触物理材质 | 小写 token：`average`、`min`、`multiply`、`max` | 默认 `average`；同一模式同时用于静摩擦和动摩擦。接触双方的模式按优先级选择后，再组合双方系数 |
| `contact.restitution_combine_mode` | `physxMaterial:restitutionCombineMode`，接触物理材质 | 同上四个小写 token | 默认 `average`；本轮仅处理普通刚体接触恢复系数，不扩展 compliant contact 的刚度语义 |

`engine_default` 是包内的明确选择，不是一个数值。USD 不为该字段创作属性值，不把 schema 的 `-inf` 哨兵当作用户显式输入。静态对象上的此类选择可记录为 `not_applicable`；不能假称静态物体有可验证的重力或阻尼积分。显式正 rest offset 与自动 contact offset 的合法性依赖引擎选值，不能只比较 USD fallback；应要求明确 contact offset 或给出准确诊断。

## 本机版本匹配的源码证据

本次已只读核对下列文件，而不是只依据在线最新版：

- `C:/isaac-sim/extscache/omni.usd.schema.physx-107.3.18+107.3.1.wx64.r.cp311.u353/plugins/PhysxSchema/resources/generatedSchema.usda`：374–378 行 angular damping，398–400 行 disableGravity，416–420 行 linear damping，516–536 行 offsets，836–844 行两项 combine mode。
- `C:/isaac-sim/extscache/omni.physx.tests-107.3.18+107.3.1.cp311.u353/omni/physxtests/tests/PhysicsCollisionAPI.py`：245–261 行 contact 的负数/相等错误测试；263–277 行 rest 的越界错误测试及 **负 rest 的正常赋值**。这是本机随发行版提供的测试代码，不等于本轮已经执行该测试。
- `C:/isaac-sim/extscache/omni.physics.tensors-107.3.18+107.3.1.wx64.r.cp311.u353/omni/physics/tensors/impl/api.py`：3720 行 `get_disable_gravities`，3957 行 `get_contact_offsets`，3982 行 `get_rest_offsets`；本轮运行验证用这些真实 backend getter，不用 USD Get 代替引擎值。

## 官方资料及其适用范围

- [Omni Physics 107.3 Colliders — rest/contact offsets](https://docs.omniverse.nvidia.com/kit/docs/omni_physics/107.3/dev_guide/rigid_bodies_articulations/collision.html#configure-rest-and-contact-offsets)：明确 rest 可正、零、负；自动 contact 与几何范围、步长等条件相关。
- [Omni Physics 107.3 Rigid Bodies — material combine modes](https://docs.omniverse.nvidia.com/kit/docs/omni_physics/107.3/dev_guide/rigid_bodies_articulations/rigid_bodies.html#configure-rigid-body-material-combine-modes)：四种模式及排序；从低到高为 average、min、multiply、max，双方取较高优先级，再分别计算静/动摩擦或恢复系数。普通刚体的 kinematic 运动规则也由该页说明。
- [Omni Physics 107.3 tensor Python API](https://docs.omniverse.nvidia.com/kit/docs/omni_physics/107.3/extensions/runtime/source/omni.physics.tensors/docs/api/python.html)：backend readback 的含义和失败契约。
- [NVIDIA PhysX 积分实现](https://github.com/NVIDIA-Omniverse/PhysX/blob/main/physx/source/lowleveldynamics/src/DyBodyCoreIntegrator.h)：23–38 行按 `1 - damping*dt` 衰减速度，由此解释插件中的 `1/s` 单位。这是官方源码的量纲依据；main 分支不是本机二进制的精确构建证明。
- [NVIDIA PhysX shape 参数检查](https://github.com/NVIDIA-Omniverse/PhysX/blob/main/physx/source/physx/src/NpShape.cpp)：`setContactOffset`/`setRestOffset` 检查有限值和严格 rest<contact。main 的 `contact>=0` 与 Omni parser 的“positive”提示不能混为一谈；本机探针单独核对 contact=0。

## 本轮运行证据

`scripts/isaac_offset_probe.py` 创建独立内存 USD cube，实际 attach、simulate/fetch 后查询 tensor offsets，并收集 parser 错误。包括负 rest、零 contact、相等/倒置 offsets 和未创作值的引擎缺省。它不修改现有产品包或导出的资产。运行结果记录在 `personal-workspace/results/sca-physics/20261019_stable_0_1_1/offset-probe*.json`；只有报告中的实际结果才属于本轮运行结论。

本轮第二次执行已完成：`offset-probe-process-02.json` 的真实返回码为 0，`offset-probe.json` 的 8 个探针均执行并符合预期。本机运行中确认 Python 3.11.13、OpenUSD 0.24.5、Isaac 5.0.0-rc.45、已加载 omni.physx 107.3.18。`contact=.005m/rest=-.001m` 被 backend 保留；`contact=0/rest=-.001m` 触发真实 PxShape 参数错误且 contact 被退回其他数值。相等、倒置和负 contact 的请求值也没有被完整保留，因而都不能声称合法。未创作 offset 的 10cm cube 得到 contact=.002m、rest=0；这是该形状的实际选值，不能硬编码成所有资产的引擎默认。

第一次执行的进程虽然返回 0，但最终 JSON 写出遇到 NumPy bool 序列化问题，未形成结果报告；`offset-probe-process.json/.log` 保留此失败。修复仅发生在探针的 JSON 输出，不改变测试条件。不能把该第一次返回码单独作为通过证据。

后续小型产品包 fixture 的运行验证分别记录：USD 创作值回读、backend getter、自由动力学行为。kinematic 的重力/阻尼仅记录保存/读回，不据此声明动力学积分效果；combine mode 的 USD 回读也不能冒充接触系数合成行为验证。

八实例的真实候选产品包 fixture 已生成并通过候选导出器导出。`isaac-rigid-report-02.json` 为 **226/226、ok=true**：backend 实际 5 dynamic、2 static、1 kinematic、0 articulation；负 rest/正 contact 的 tensor getter、gravity flag、材质注册路径和原有三接触系数/质量均通过。初始激励仅为 vx=.2m/s 和 wz=2rad/s，未改资产参数。0.2s 后，linear damping=2.4 的 vx=.123458065m/s，angular damping=1.8 的 wz=1.393458247rad/s，分别符合 `c*dt` 衰减；0 控制、重力下落和无重力保持也分别核对。依赖文件 SHA 及阶段内物理配置前后不变。

`isaac-rigid-report-01.json` 保留首次 checker 的不通过结果：旧导出器没有创作可选 `enableGPUDynamics=false`，checker 错将“没有创作”当作失败；该字段并不在八项扩展要求内。修复 checker 后以实际 CPU tensor device 验证运行环境，未向资产补写任何场景/求解参数。进程记录分别为同名 `isaac-rigid-process-*.json/.log`；仍须联合检查 JSON 的 ok 与真实过程状态，不能仅凭 Kit 返回码判定通过。
