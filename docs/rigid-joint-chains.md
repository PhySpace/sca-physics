# CAD 后附加圆截面刚体关节链

当前版本0.1.8rc1，配套USD0.1.8rc2。仅链声明的新写入metadata schema1.7；含新关节/Articulation/耦合字段时使用1.8。旧1.4–1.6原样读取/导出，不重选N或重标来源。新声明physics_hz限1..16384、position iterations1..255、velocity iterations0..255；允许保存不代表收敛。旧1.4限4096Hz，旧1.4/1.5分段2..512；预算合同1.6–1.8可允许更多。来源与圆杆换算见[Agent决策](agent-decisions.zh-CN.md)，预设入口见[自动线缆](automatic-cables.zh-CN.md)。`cables[id].representation="rigid_joint_chain"` 对应 `parts[target].physical_type="rigid_joint_chain"`；FEM不能同时绑定一个occurrence。

`upsert_rigid_chain()`保存实际CAD BREP摘要、原生mm、世界变换SI和定义身份。旧手工入口中心线由调用者提供；新描述入口可读取完整实心直圆柱的实际轴/尺寸，插件没有从任意BREP自动提取中心线，也没有证明中心线处处在CAD内部，这些假设须记录于source。

```python
from sca_physics.rigid_chain import upsert_rigid_chain
from sca_physics.package_io import enrich_package, write_new
from simplecadapi import read_product_package, encode_product_package

package = read_product_package(data=input_path)
config = upsert_rigid_chain(package, target_node_id, declaration,
    chain_id="cable", convert_rigid=False, replace_deformable=False)
updated, preservation = enrich_package(package, config)
write_new(output_path, encode_product_package(updated))
```

全部下列group与source均必需，无材料默认；仅表中明确标注的可选开关可以省略。数值/数组可简写，保存为 `{value,unit,source}`，逐值source优先于组source，再继承顶层source；无任何来源则拒绝字段，不自动标用户。修改已有explicit用户参数须有新的explicit用户来源，estimated不得覆盖；完整声明可带decision，保存到根config而非cables记录。独立持久化校验要求wrapper完整；未知字段、错单位、非有限值、布尔冒充数值拒绝。API的base_config/CLI的--base-config只允许没有sca_physics的raw包，在一次保存中设置基础实例配置。

| group | 字段及单位 |
|---|---|
| geometry | coordinate_space="world",initial_shape="planar"；centerline为3D点数组(m)，arc_stations(m)同点数从0严格递增；free_start/free_end/length(m) |
| discretization | free_segments(count,旧1.4/1.5为2..512；1.6/1.7为≥2并由resource_budget限制),frame_policy="shortest_arc_x" |
| section | shape="circle",radius/endpoint_radius(m) |
| mechanics | linear_density(kg/m),bending_rigidity/torsional_rigidity(N*m^2),joint_damping(N*m*s/rad),damping_mode="per_joint",rest_state="straight" |
| limits | minimum_bend_radius(m),maximum_bend_angle/maximum_twist_angle(deg,0..180开区间) |
| body | linear_damping/angular_damping(1/s),solver_position_iterations(1..255),solver_velocity_iterations(0..255),enable_speculative_ccd/apply_to_endpoints(boolean) |
| collision | enabled/self_collision/filter_adjacent/filter_endpoint_links(boolean),contact_offset/rest_offset(m)；filter_adjacent必须true，contact>0、rest<contact；可选filter_material_neighbors(boolean，省略保存false默认及来源) |
| contact | static_friction/dynamic_friction/restitution(1)，恢复系数0..1 |
| scene | physics_hz(count),gravity_magnitude(m/s^2),solver_type="TGS",enable_gpu_dynamics=false,broadphase_type="MBP" |
| endpoints | start/end各为 `{mode:"free"}`、`{mode:"world_fixed"}`或`{mode:"body_fixed",rigid_node_id:"另一真实part ID"}` |

free_segments仅分割free_start..free_end，两侧非零端区间各额外一段；free_start=0、free_end=length时无额外端段。端frame由初始端段切线和端body的世界变换派生，不接受自定义frame。目标参与原生ground/joint时拒绝，不能丢关系；链/FEM目标不能作为另一链刚体端点。

导出沿用V6：m=λΔs，圆capsule为几何/碰撞/惯量代理；D6平移锁定，k_bend=EI/平均相邻段长，k_twist=GJ/同长度。每joint c保持其原单位，不随N重新解释。angular force drive使用degrees，SI(rad)参数乘π/180并换算stage质量/长度单位。capsule height为中心线弦长，端帽伸出端点，故相邻过滤必需。

这些公式描述当前声明到USD的参数映射，**不代表等效连续体精度已通过**。历史rc1的20/40/80段受控恒载试验出现显著响应差异，扭转理论检查失败；rc2的精细求解设置降低了这些量值偏差，但原严格瞬时静态判据仍失败，不能用于宣称分段无关的工程刚度或实物标定结果。详见 [验证状态](validation.zh-CN.md)。

当分段长度接近线径时，非相邻胶囊的圆端帽也可能在同一局部材料邻域内重叠。显式 `filter_material_neighbors=true` 额外过滤两段材料区间之间弧长间隙不大于两半径之和的 pair；只按材料坐标选择，不按当前空间距离关闭接触。远弧长折回的段仍保留 self collision。V6 回归保持 false；新最小例显式 true。早期本候选1.4包省略该可选字段时按 false 读取，校验不修改原 metadata。

直线自然态不同于初始CAD曲率；初始弯曲相对零角目标有弹性载荷，可能回弹。分轴bend limit不是严格三维最小曲率保证；per_joint c不具有分段无关耗散。EI/GJ不是FEM的E/ν，不证明真实多芯线缆标定。

body.apply_to_endpoints仅将solver iterations和预测式CCD应用到所选body_fixed端actor，不覆盖端body阻尼/kinematic模式；模式仍由parts.rigid_body声明。多链场景设置、共享端actor配置冲突由USD导出拒绝。CPU刚体链与要求GPU的FEM同场景首版明确拒绝，保存声明不代表可共同求解。

## 离散长度与力学对照

当前模型以材料区间为刚体，以相邻区间中点之间的材料长度 `ell_i=(ds_i+ds_(i+1))/2` 分配弹簧柔度。N个全自由区间只有N−1个内部D6；`world_fixed`/`body_fixed`的端部FixedJoint不增加弹性柔度。因此在直线、小转角、纯端扭矩且达到静态平衡时，应同时核对：

- 当前离散模型：`phi=T*sum(1/k_i)`，`k_i=GJ/ell_i`。
- 连续等截面杆：`phi=T*L/GJ`。

内部弹簧代表的长度总和是 `L-(ds_first+ds_last)/2`；两端半区间保留为刚体，没有凭空增加弹性端部关节。全长均匀N段的离散/连续柔度比为 `(N−1)/N`，是需随加密检查的边界离散误差，不能通过修改材料刚度补偿。两个非自由端区间也使用同一材料公式，并不自动成为完全刚性的夹持材料。必须按实际区间逐项求和，不能仅用free_segments计算总关节数或假定柔性长度等于free_end−free_start。

2026-10-21失败案例的总材料长250mm、自由区[5,245]mm、两侧各一个5mm端区间；N20/40/80分别有22/42/82段和21/41/81个内部D6。三种离散弹簧长度总和均为245mm，给定GJ与扭矩的离散参考均为0.0245rad；旧连续杆参考0.025rad仍保留。2%的边界差不能解释原大幅过软。

静态角度曲线变平不是平衡的充分条件。原生验证须同时记录实际USD驱动值、原生质量/惯量、位姿差分速度、原生速度、各关节角度和载荷平衡，并在同一N下先检查时间步/迭代收敛，再比较N。`per_joint`阻尼不具备分段无关的动态耗散，不能把未平衡的动态结果当作静态刚度。TGS对子步与耦合约束敏感；单独提高迭代数、打开外力子步开关或能运行到结束，都不是工程精度验收。
