# Agent 决策与严格来源（0.1.8rc1 / Schema1.7–1.8）

Agent 理解需求，选择当前实现能够表达的模型，查找适用资料或给出有依据的工程估计。插件只做确定性计算、输入校验、产品包保存与回读；它不联网分类，不验证材料声明是否真实，也不以运行完成证明物理精度。

三条路径：普通刚体用 enrich 附加已实现的接触、碰撞、模式和阻尼等字段，密度仍来自原生 SCA 材料；适合两类整线预设的对象显式选 category 后用 configure-cable；其他满足圆截面、平面初态、直线自然态、不可伸长近似的细长体，用完整 set-rigid-chain。有限拉伸、分叉、扁带、多芯内部结构、空间初态或无应力曲线自然态不在现有链模型范围。

## 提交值及来源

保存的参数为 `{value,unit,source}`，来源有 explicit、reference、estimated、default、derived。explicit只用于用户确实给定的值；Agent估计使用estimated，detail记录物体、依据、假设与适用条件；reference另需citation和conditions。来源真实性由调用者负责。

新输入可在值、组或声明根提供source；逐值覆盖组，组覆盖根。没有任一来源的裸值或简写wrapper拒绝并指出字段，不自动标explicit。规则同样覆盖geometry、discretization的N/h、solver和resource_budget；输入0/false保留。程序缺省值仍标default，不冒充根来源。engine_default是已有字段对引擎的明确委托，不是已测数值。

```json
{
  "description":"按当前任务确认适用的多股电线",
  "category":"stranded_wire",
  "source":{"kind":"estimated","detail":"针对当前构造的初始估计；假设须另述"},
  "properties":{
    "linear_density":0.018,
    "gravity_magnitude":{"value":0,"unit":"m/s^2","source":{"kind":"explicit","detail":"用户要求无重力实验"}}
  },
  "discretization":{"mode":"target_length","target_segment_length_m":0.02},
  "solver":{"physics_hz":1200}
}
```

configure-cable使用本次合法properties，再用evidence补缺，最后用预设补缺；不会因estimated标签而舍弃提交线密度。调用者提交前须保留用户要求并处理资料取舍。λ和等效ρ在同层互斥，ρ按实际圆截面转为derived λ。explicit/target_length/auto互斥，g=0时自动选段不使用弹性重力特征长度。当前选段仍是初始工程规则，不能代替用途和收敛判断。

对已有对象显式 --reconfigure 从实际已保存wrapper继续，包括default/estimated、N、solver和预算；仅新提交同名值替换，不重读旧raw值赋予新来源。保存的explicit用户参数只能由新的explicit用户来源修改；λ/ρ同族允许用户明确ρ经受支持公式换算后修订λ，并继续保留该用户权威。Agent估计及任意derived记录不能绕过保护。仅改“较硬”标签不会重新套预设；改变实际EI/GJ须给新的有来源数值。description不解析硬度关键词；fresh预设显式feel=stiffer/softer仍只是2/0.5工程档位，省略normal。

## 圆杆公开换算

仅对均匀实心圆杆或已明确接受该等效假设的对象，采用 `A=πd²/4`、`I=πd⁴/64`、`J=πd⁴/32`，由 `λ=ρA`、`EI=E·I`、`GJ=G·J` 计算。多股、复合线的整线有效EI/GJ通常不能从纯材料E乘整个外径截面得到，适合时直接提交有依据的整线等效参数。

```python
from sca_physics import circle_rod

estimate = {"kind": "estimated", "detail": "当前等效圆杆的工程估计及适用假设"}
mechanics = circle_rod(
    diameter_m=0.005, density_kg_m3=1200,
    youngs_modulus_pa=2e7, shear_modulus_pa=7e6, source=estimate,
)
# 将三个返回wrapper合并到完整声明的mechanics，其他必填字段另行提供。
```

每个参数也可单独传入value/unit/source，覆盖source参数。输出键为linear_density、bending_rigidity、torsional_rigidity；均为标准wrapper。source.kind=derived，derivation保存rule、固定formula及完整有来源inputs。支持规则包括圆杆三式、由λ/圆面积求ρ、mm到m、标量缩放、直径幂缩放、折线弧长/站点、差值与 `N=max(2,ceil(L/h))`；规则表在src/sca_physics/provenance.py。

调用者可用 `from sca_physics.provenance import derived` 生成其他已支持换算，例如 `derived("segment-count-v1", {"length": L_wrapper, "target_length": h_wrapper}, "当前分辨率依据")`。helper输出可以序列化到任务JSON再交给set-rigid-chain；读取会核对受支持规则、固定公式、输入单位并重算结果，拒绝仅写kind=derived、缺输入、改公式或改结果的记录。该核对不确认输入来源或材料真实性，也不执行任意公式代码。

## 保存决策并关联字段

根输入可加decision，必需purpose、representation、rationale非空文本，可加assumptions/limitations字符串数组。bindings可关联实际保存参数、任务材料标识与依据：

```json
{
  "purpose":"指定动作下的细长杆近似",
  "representation":"rigid_joint_chain",
  "rationale":"选择圆杆近似并说明材料和分段依据",
  "bindings":[{
    "field":"/cables/object/mechanics/linear_density",
    "material_id":"equivalent_rod",
    "basis":"按该任务估计密度和实际直径换算"
  }]
}
```

field推荐JSON Pointer，ID含`/`时转义为`~1`；也支持简单点路径。程序要求其确实指向保存的参数wrapper；material_id为调用者声明的材料/等效材料标识，不冒充原生材料库已核验ID。独立inspect/validate和USD导出只读最终包，不再次查询预设、猜材料或选段。

新1.7预算六项保存count单位及来源，budget_values可只读解包；为不伪造旧来源，保留的历史数字预算也可继续读。旧1.0–1.6包原样校验/导出，不补新来源、不升级schema、不改N。新写入才采用1.7严格输入；历史包中的explicit标签不是本次重新确认的用户证词。
