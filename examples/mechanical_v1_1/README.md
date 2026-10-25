# 机械参数最小验收示例

`cube.py` 是原生 SCA 10 mm 立方体，`assembly.py` 创建八个独立实例，只有 anchor 原生 ground。`physics-input.json` 用准确 node_id 声明模式、0/false、偏置和 engine_default。数值是软件验收输入，不是材料实测值。

调用者明确设置：$ScaPython 为 SCA 2.2.5 建模解释器，$PhysicsPython / $UsdPython 分别为 physics 0.1.8rc1 / USD 0.1.8rc2 配套独立运行环境，$RepoRoot 为当前仓库根，$Run 为尚不存在的绝对输出目录。

```powershell
New-Item -ItemType Directory -Path $Run | Out-Null
Copy-Item -LiteralPath "$RepoRoot/examples/mechanical_v1_1/assembly.py", "$RepoRoot/examples/mechanical_v1_1/cube.py" -Destination $Run
& $ScaPython -I -B -m simplecadapi.cli run "$Run/assembly.py" --out "$Run/raw.scadpkg" --no-cache
if ($LASTEXITCODE) { throw 'CAD capture failed' }
& $PhysicsPython -I -B -m sca_physics inspect "$Run/raw.scadpkg"
& $PhysicsPython -I -B -m sca_physics template "$Run/raw.scadpkg" --include-mechanical --output "$Run/template.json"
& $PhysicsPython -I -B -m sca_physics enrich "$Run/raw.scadpkg" --config "$RepoRoot/examples/mechanical_v1_1/physics-input.json" --output "$Run/final.scadpkg"
if ($LASTEXITCODE) { throw 'physics attachment failed' }
& $PhysicsPython -I -B -m sca_physics validate "$Run/final.scadpkg"
if ($LASTEXITCODE) { throw 'package validation failed' }
& $UsdPython -I -B -m sca_usd_export export "$Run/final.scadpkg" "$Run/final.usda"
if ($LASTEXITCODE) { throw 'USD export failed' }
& $UsdPython -I -B -m sca_usd_export validate "$Run/final.usda"
if ($LASTEXITCODE) { throw 'USD reopen failed' }
```

默认 template 仍为 schema 1.0，template --include-mechanical 显式输出 1.1；本例输入也显式选择 1.1。当前未指定schema的新输入使用1.7，新关节字段使用1.8，不再单凭机械字段自动选择1.1。engine_default 表示不写对应 USD opinion，不能与数值混写。静态对象的刚体重力/阻尼由导出拒绝；运动学对象的该类属性不会产生动态积分效果。

外部 Isaac 探针为 `scripts/isaac_rigid_fields_check.py --usd ... --expect ... --report 新文件.json`。expect 的实际路径必须来自该次导出 report，不猜测顺序。该脚本只施加初始速度，不补写被测参数。属性与绑定检查不代表滑动或回弹试验完成。
