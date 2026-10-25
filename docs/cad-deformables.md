# 选择已有 CAD 实例后附加体可变形声明

此接口继承自 0.1.5rc1，当前候选为本插件0.1.8rc1与配套 `sca-usd-export==0.1.8rc2`；本轮没有改变FEM算法。产品包仍通过 `enrich_package()`
保存根定义 `metadata.sca_physics`；原1.3 CAD绑定合同保留，新写入1.7，不引入 PhysicsDocument。
选择发生在下面的 `target_node_id` / CLI `--target` 参数，必须是 `inspect` 返回的
**精确 occurrence node_id**。定义 ID 或显示名不是选择器。两个实例共享同一零件定义时，
只改变所选实例的物理声明，不编辑共享 CAD 定义。

Python 薄接口：

```python
from simplecadapi import read_product_package, encode_product_package
from sca_physics.deformable import upsert_deformable_volume
from sca_physics.package_io import enrich_package, write_new

package = read_product_package(data="cad-cable.physics.scadpkg")
target = "node/dual_connector_cable_demo/cable"
config = upsert_deformable_volume(package, target, material={
    "source": {"kind": "estimated", "detail": "当前物体的工程材料估计；需说明依据和适用条件"},
    "youngs_modulus": {"value": 2e8, "unit": "Pa"},
    "poissons_ratio": {"value": .35, "unit": "1"},
    "density": {"value": 1200., "unit": "kg/m^3"},
})
updated, preservation = enrich_package(package, config)
write_new("cad-cable.E200MPa.scadpkg", encode_product_package(updated))
```

首次附加传入完整 `declaration`，包含实际 CAD 闭合表面经官方 cooking 生成并冻结的
`simulation_mesh.generated`、材料和两端附件。后续仅传 `material` 即修改原记录，
保留原 cable_id、target_node_id、CAD/BREP、参考点、拓扑、节点选择及观测映射。
`material` 还接受 `dynamic_friction` 与 `elasticity_damping`（1/s）。
`deformable.linear_damping`、`settling_damping` 为 1/s，`sleep_threshold`、
`settling_threshold` 为 m/s；可省略字段不补默认。非实时热更新，导出后重新加载。新传入material的逐值来源覆盖本次material组source；不借上次声明来源给新裸值补身份，无来源拒绝。

CLI 与 Python 接口相同。相对路径按当前工作目录解析；输出独占创建，不能覆盖已有文件：

```powershell
# $pair 为调用者明确选择的 USD0.1.8rc2 + physics0.1.8rc1 独立 runtime Python 绝对路径。
& $pair -I -B -m sca_physics inspect .\raw.scadpkg
& $pair -I -B -m sca_physics set-deformable .\raw.scadpkg --target 'node/dual_connector_cable_demo/cable' --config .\cad-declaration.json --output .\cad-cable.physics.scadpkg
& $pair -I -B -m sca_physics set-deformable .\cad-cable.physics.scadpkg --target 'node/dual_connector_cable_demo/cable' --material .\material.json --output .\cad-cable.updated.scadpkg
& $pair -I -B -m sca_physics validate .\cad-cable.updated.scadpkg
```

`material.json` 例：`{"source":{"kind":"estimated","detail":"当前物体的工程材料估计；需说明依据和适用条件"},"youngs_modulus":200000000,"poissons_ratio":0.35,"density":1200}`。
此处接口用法不代替项目交付中的实际文件名、cooking 及 USD 导出命令。

声明新增字段：

- `target_node_id`、`physical_type:"deformable_volume"`；对应 `parts[target]` 同样标注
  `physical_type`，并禁止 `rigid_body` 块。已有 rigid_body 配置必须由调用者显式
  `convert_rigid=True` / `--convert-rigid` 移除；其他实例保持不变。
- `geometry_source`：`geometry_source_snapshot(package, target)` 从官方产品包读取目标定义、
  实际 BREP 字节摘要、原生 mm、持久化网格 m、通过官方 placement decoder 解析的世界 SI
  变换及摘要。`definition_content_hash` 是排除自身 `sca_physics` 与原摘要字段后的规范化
  定义摘要，避免单零件根定义的后附加元数据导致自我失效。其余 CAD 语义保留。
- `simulation_mesh.generation_config`：有限 JSON，明确保存 tessellation/cooking 配置；
  `cache_key` 与 `generated.mesh_cache_key` 必须同时等于
  `mesh_cache_key(geometry_source, simulation_mesh)`。材料及来源文字不参与缓存 key。
- `generated.source_geometry_sha256`：实际 CAD 变换后闭合表面摘要，由导出端再次三角化
  核对；`mesh_sha256` 校验实际 float32 points、int32 tets、int32 surface。参考构形为
  无预应变初始点。重选端点及中心线映射随同一次生成结果保存。

改变 BREP、CAD 定义、影响几何的变换/缩放、原生单位或 mesh 配置，会明确拒绝旧缓存，
要求重新生成整组网格、端部索引与映射，不自动继承旧节点索引。改变材料不触发 cooking。
`geometry.centerline/diameter/length` 在这个兼容线缆接口中仍用于范围、截面、附件和观测校验；
网格几何来源是被选 CAD/BREP，不是这些测量字段生成的扫掠替身。本候选接口仍针对有两个
明确端截面的线缆类零件；任意形状和任意数量附件的通用编辑器不在此次范围。

柔体密度由 `cables[id].material.density`（kg/m³）权威提供。所选目标不进入刚体分组、
刚体显式质量或刚性 collider 处理，原生 CAD 材料密度不覆盖它。CAD 中的原始材料信息保持
不变；修改柔体密度不会被旧刚体质量遮蔽。导出报告的密度×体积是声明推算，不能冒称原生
逐节点质量 getter 的读取证据。

原生固定、接地及 joint 若涉及目标或其 grounded 祖先，当前明确拒绝，需调用者在建模时
表达预期的自由目标，再以支持的 FEM 端区域附件连接；不会静默丢弃关系。附件不能把另一个
柔体当作 rigid endpoint。端部碰撞过滤以显式 m 长度保存。

兼容性：schema 1.0/1.1 与旧无 CAD 目标的 schema 1.2 均保留；旧 swept 分支仍存在于旧
声明，但 CAD 目标只接受实际官方生成并持久化的网格。已有包可经
`enrich_package(package, explicit_full_config)` 更新；无参数重复 enrich 保留原来的拒绝行为，
避免无意用默认值覆盖已有材料。始终另存完整产品包，不覆盖历史资产。

标准库测试入口（在已安装配套环境运行）：

```powershell
& $pair -I -B "$RepoRoot/tests/test_cad_deformable.py" --package "$CadFemPackage" -v
```

这些边界测试不代表 PhysX 初始化或材料行为已经通过；两者必须由项目独立验证结果判定。
