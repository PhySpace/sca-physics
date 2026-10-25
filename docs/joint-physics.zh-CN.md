# 关节参数、主动执行器与部分更新（Schema 1.8）

`enrich`、`update` 和 Python `update_config` / `update_package` 是公开入口。SCA 原生旋转副、移动副及稳定 `joint_id` 提供父子连接器、两端局部位置与旋转、轴、零位和正方向。本插件不按外观重新建副、不覆盖这些原生坐标，也不声明电机电气模型、转子惯量或减速比。

无新增关节/Articulation 字段的新配置仍默认 Schema 1.7；含下列新字段且未指定版本时使用 1.8。显式 1.0–1.7 混入新字段立即拒绝。旧包只读不改版本、来源、线缆分段或自然态；不支持 1.8 的旧导出器必须报不支持 schema，不能丢弃字段继续导出。

## 逐实例关节字段

全部参数在最终包内保存 `{value,unit,source}`。稀疏输入允许从字段、drive 组、joint 组、声明根继承最近的来源；缺来源拒绝。`explicit` 只用于用户实际给出的数值；试验限位、试验增益和数值占位用 `estimated` 并说明用途。字段省略时不补新默认、不写新的 USD opinion；`0`、`false` 原样保留。这些新字段不支持 `engine_default`。

| `joints[joint_id]` 字段 | revolute 单位 | prismatic 单位 | 约束 |
|---|---|---|---|
| motion | token | token | free / limited；省略沿用旧导出行为 |
| lower_limit、upper_limit | rad | m | limited 必须两者完整且 lower < upper；free 或省略 motion 时不许带限位 |
| max_velocity | rad/s | m/s | 有限非负；PhysX 后端需要启用有效 Articulation |
| friction | 1 | 1 | 有限非负关节摩擦系数；PhysX 后端需要有效 Articulation |
| damping（旧字段） | N*m*s/rad | N*s/m | 纯被动关节耗散系数 |
| drive.mode | token | token | off / position / velocity；控制方式 |
| drive.type | token | token | 当前仅 force；底层驱动类型，与 mode 分开 |
| drive.target_position | rad | m | 有符号有限值；position 模式下必须在显式运动限位内 |
| drive.target_velocity | rad/s | m/s | 有符号有限值 |
| drive.stiffness | N*m/rad | N/m | 有限非负；position 必须 > 0；velocity 必须 = 0 |
| drive.damping | N*m*s/rad | N*s/m | 有限非负；velocity 必须 > 0 |
| drive.max_force | N*m | N | 有限正值；配置输出上限，不是实测值或真实电机额定值 |

提交 drive 时七项必须完整；用 `update` 更新已有 drive 的一个字段时会保留其他六项。数值必须可表达为有限 USD float32；不许非零数下溢为 0。lower/upper 转 float32 后也须保持严格大小关系。其他原生副类型拒绝上述新关节字段；原来固定副 damping=0/unit=unsupported 规则保留。

`assembly.articulation` 的完整块为 `{enabled:{value:true,unit:"boolean",source:...},root_node_id:"实际node_id",fixed_base:{value:true,unit:"boolean",source:...}}`。root_node_id 必须是产品包根或某个真实零件实例，不许显示名、定义 ID 或其他嵌套装配。保存阶段核对身份；导出阶段进一步检查固定组归并后的根、父子图、连通性、闭环、支持的自由度与固定基座关系。仅保存 enabled 或看到 ArticulationRootAPI 不代表树拓扑和求解器有效。非零原生关节初态由配套导出器保留零位并显式映射，不通过重设 Transform 归零。

可选 `assembly.articulation.self_collisions` 为有来源的 boolean wrapper，仅显式提供才保存；省略时配套导出器明确采用并报告 true，以保留非相邻实际接触。逐对过滤仍由 collision_exclusions 和原生关节 collision_enabled 声明，不能用关闭整棵树自碰撞掩盖必要接触。

## 位置驱动最小声明

先 `inspect` 获取真实 ID。下面数值仅用于软件功能示例；角度 15°以弧度写入，其他参数必须由调用者说明实际用途与来源。

```json
{
  "source":{"kind":"estimated","detail":"15度位置驱动的软件功能实验；增益、阻尼及上限未作硬件标定"},
  "joints":{
    "替换为实际joint_id":{
      "motion":"limited","lower_limit":-0.7853981633974483,"upper_limit":0.7853981633974483,
      "damping":0.02,
      "drive":{"mode":"position","type":"force","target_position":0.2617993877991494,
        "target_velocity":0,"stiffness":2,"damping":0.4,"max_force":3}
    }
  }
}
```

```text
enrich raw.scadpkg --config joint-input.json --output driven.scadpkg
update driven.scadpkg --config target-patch.json --output next-target.scadpkg
validate next-target.scadpkg --expect expected-snapshot.json
```

`target-patch.json` 只需 `{"joints":{"实际joint_id":{"drive":{"target_position":{"value":0.1,"unit":"rad","source":{"kind":"estimated","detail":"第二个软件测试目标，非硬件指令规格"}}}}}}`。如果原目标来源为 explicit，新值也必须由新的 explicit 用户来源授权；Agent 估计不能覆盖用户参数。

```python
import simplecadapi as scad
from sca_physics import update_package

package = scad.read_product_package(data="driven.scadpkg")
updated, report = update_package(package, patch)
# updated 是经过官方 build/encode/read、严格验证和保留检查的完整包。
with open("new-target.scadpkg", "xb") as output:
    output.write(scad.encode_product_package(updated))
```

`update_config(package, patch)` 返回完整配置而不修改输入；`update_package` 通过相同官方重建与保留检查保存，不是绕过产品包的专用通道。两者要求现有 sca_physics 完整且合法；raw 包用 enrich。字典按字段合并，参数 wrapper 和列表整体替换，不支持 null/删除语法。更新一个 wrapper 不从旧 wrapper 继承 source 或 unit；新的值必须携带新来源或显式继承本次 patch 的组来源。其他已有 wrapper、来源、未改线缆声明逐字保留。未显式指定版本的 patch 引入新能力时允许自动升级到 1.8，报告记录前后版本；普通旧字段更新保留原版本。需要删除旧限位、完整替换表示等结构变化时，提供审阅过的完整配置给 enrich。

## 被动阻尼与主动驱动的单通道组合

设被动关节阻尼为 Dp，启用驱动的阻尼为 Da、刚度为 K、目标速度为 vt。力/力矩形式为 `K*(target_position-q) + Da*(vt-v) - Dp*v`。配套导出器用单个 force Drive 表达：`Dtotal=Dp+Da`、`target_velocity_effective=Da/Dtotal*vt`（总阻尼为 0 时用 0），K 保持。这样保留主动速度项与独立被动耗散，避免双重阻尼或覆盖。drive.mode=off 时忽略主动 K/Da/目标/输出上限，恢复旧 passive 行为。

后端只提供这一组合通道，所以 max_force 对组合后的总 Drive 限幅，不能分别限制主动输出而让被动阻尼无限制。若任务需要独立电机限流与独立被动阻尼饱和，这个近似不够。关节摩擦按受约束负载产生的摩擦语义处理，不是常数制动力矩；接触摩擦是材料接触属性，刚体角阻尼是 1/s 的整体衰减，均不能替代关节阻尼或 drive.damping。

产品包使用 SI，USD stage 为 m/kg 时，角目标/速度从 rad 转 degree；角刚度和角阻尼都乘 π/180，线性参数保持 SI。Max Torque 仍是 N*m，惯量仍是 kg*m²，不能把所有角参数一律乘 180/π。运行时只能更新正式 USD 中已有 drive 的目标；组合通道的速度目标更新还须使用 `Da/Dtotal` 权重。运行脚本不应临时补建缺失 DriveAPI、限位或增益来冒充正式导出。

保存/回读、USD 属性重开、PhysX 有效初始化、真实跟踪/限位/接触行为分别验收。此接口不证明硬件动力学校准、稳定抓取或理想传动耦合成立；耦合需要另行明确声明和实测。

## 最小齿轮齿条 Mimic

顶层可选 `couplings[id]` 保存 `representation:"mimic"`、`reference_joint_id`、`follower_joint_id`、`gearing`（m/rad wrapper）、`offset`（m wrapper）和声明 `source`。其理想约束为 `q_follower + gearing*q_reference + offset = 0`；gearing 有符号、有限且非零，offset 有符号且有限。source 支持声明根继承，保存时两个数值都保留完整 value/unit/source。比如半径 6mm、滑动正方向与旋转正方向按上式相反时 gearing=0.006；该示例不能用于猜测未知夹爪的实际齿数或节圆半径。

只支持原生 revolute reference → prismatic follower。两者都必须声明有限 limited 范围、存在可行的运动区间，并属于同一个已请求启用、实际有效的 Articulation；后者由导出器验证。一个 reference 可以带多个 follower，但每个 follower 只能有一个 owner。反向类型、循环/链式传动和其他表示拒绝。follower.drive 必须省略或 off，旧 passive damping 必须为 0，配套导出器不为 follower 创建独立 DriveAPI；不能逐帧给两个位置目标冒充约束。

```json
{
  "source":{"kind":"reference","detail":"来自实际齿条/齿轮几何与方向约定","citation":"替换为可追溯的模型来源","conditions":"理想刚性传动，无齿隙、弹性或齿面接触"},
  "couplings":{"rack_a":{"representation":"mimic","reference_joint_id":"实际旋转副joint_id",
    "follower_joint_id":"实际移动副joint_id","gearing":0.006,"offset":0}}
}
```

以上是附加到完整已限位且已启用 Articulation 配置的稀疏 patch；使用 `update` 时保持所有其他参数。新值须携带本次 patch 的字段/组来源，不能沿用旧耦合记录 source 为新数值背书。正负方向、参考零位与偏置由显式方程定义，导出器对照实际求解后的原生 CAD 初态检查一致性；不一致时拒绝，不靠调整 Transform 修复。USD angular 坐标使用 degree，m 场景的底层 gearing 为 `gearing_SI*π/180`，offset 保持 m；其他 stage 长度单位再做长度缩放。

此模型依赖本机 PhysX Mimic 机制，仅近似运动学传动与约束传力；不模拟齿面滚动/滑动、齿隙、啮合冲击、齿轮弹性、效率或电机电气行为。碰撞代理和逐对过滤需与理想约束相容；必要的夹爪/被抓物体接触仍须保留，并单独用真实求解数据验收。
