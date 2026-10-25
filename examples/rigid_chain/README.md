# 最小圆线缆示例

`cable.py` 和 `assembly.py` 仅创建原生 CAD，`chain.json` 明确提供世界 SI 中心线和工程演示参数。没有分段、惯量或关节算法；这些由配套 USD 插件生成。样例的 CAD 材料密度保持原生信息，链质量采用明确的单位长度质量 `0.02 kg/m`，不能视为同质材料标定。

完整字段见 [显式声明合同](../../docs/rigid-joint-chains.md)，按任务选择预设或自定义声明见 [细长体流程](../../docs/automatic-cables.zh-CN.md)。本例的16段、480Hz及其余数值仅演示声明格式和保存/独立导出，不是其他细长体的推荐参数或动力学验收结论。自定义对象需重新判断模型适用性、几何、物性、段数和边界；估计来源用 estimated，用户明确提供的值逐项保留其来源。

以下变量须先指向已安装的独立环境、仓库根及尚未存在的输出目录；不要修改全局 stable：

```powershell
# $ScaPython: 带 SimpleCADAPI 2.2.5 的建模解释器
# $PhysicsPython / $UsdPython: physics0.1.8rc1 / USD0.1.8rc2 的配套独立 runtime Python
# $RepoRoot: 此 sca-physics 仓库根；$Run: 新的绝对输出目录
New-Item -ItemType Directory -Path $Run | Out-Null
# scad.use 会在脚本旁缓存；先复制CAD源码，确保缓存留在结果目录。
Copy-Item -LiteralPath "$RepoRoot/examples/rigid_chain/assembly.py", "$RepoRoot/examples/rigid_chain/cable.py" -Destination $Run
& $ScaPython -I -B -m simplecadapi.cli run "$Run/assembly.py" --out "$Run/raw.scadpkg" --no-cache
if ($LASTEXITCODE) { throw 'CAD capture failed' }
& $PhysicsPython -I -B -m sca_physics inspect "$Run/raw.scadpkg"
& $PhysicsPython -I -B -m sca_physics set-rigid-chain "$Run/raw.scadpkg" --target 'node/round_cable_demo/wire' --chain-id wire --config "$RepoRoot/examples/rigid_chain/chain.json" --output "$Run/final.scadpkg"
if ($LASTEXITCODE) { throw 'physics attachment failed' }
# 下面每条命令是新进程，只使用持久化包，不再传 chain.json。
& $PhysicsPython -I -B -m sca_physics validate "$Run/final.scadpkg"
if ($LASTEXITCODE) { throw 'package validation failed' }
& $UsdPython -I -B -m sca_usd_export export "$Run/final.scadpkg" "$Run/final.usda"
if ($LASTEXITCODE) { throw 'USD export failed' }
& $UsdPython -I -B -m sca_usd_export validate "$Run/final.usda"
if ($LASTEXITCODE) { throw 'USD reopen validation failed' }
```

重开成功只证明 USD 配置和结构，不代表原生动力学通过。使用外部 Isaac Sim 打开导出场景时，仍需确认其原生日志和行为；本仓库不分发 Isaac/PhysX。
