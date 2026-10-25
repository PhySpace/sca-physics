# 独立安装与维护

Windows x86-64、CPython3.12、SimpleCADAPI2.2.5。仓库根的sca-addon.toml提供name/version/skill/compat/runtime，pyproject提供Python安装。对现有机器应新建独立home/skills-dir/runtime验收，不替换其他Agent的入口。

实际SCA2.2.5 CLI格式如下，所有变量由使用者明确指定，不内置个人路径。以下整组命令必须在同一个PowerShell进程中顺序执行，使用同一个宿主解释器、home、skills-dir和USERPROFILE上下文：

普通用户安装使用该进程现有的USERPROFILE。`init`和`addon add`会创建或更新该用户的`.sca/config.toml`；显式`--home`、`--skills-dir`和`--no-shell`不表示不写用户配置，`--no-shell`仅避免配置shell。

隔离验收应先启动专用PowerShell子进程，并在该子进程中、执行整组命令之前运行下面的设置。`$AuditUserProfile`必须是调用者指定的全新隔离目录，不能指向真实用户目录。随后所有SCA命令及其启动的子进程继承同一上下文，不要仅为`init`单独重定向USERPROFILE：

```powershell
New-Item -ItemType Directory -Path $AuditUserProfile -ErrorAction Stop | Out-Null
$env:USERPROFILE = (Resolve-Path -LiteralPath $AuditUserProfile).Path
$env:APPDATA = Join-Path $env:USERPROFILE 'AppData/Roaming'
$env:LOCALAPPDATA = Join-Path $env:USERPROFILE 'AppData/Local'
& $ScaPython -I -B -c 'import sys; from pathlib import Path; actual = Path.home().resolve(); expected = Path(sys.argv[1]).resolve(); print(actual); assert actual == expected' $env:USERPROFILE
if ($LASTEXITCODE) { throw 'isolated USERPROFILE check failed' }
```

然后在同一个进程中执行安装；真实用户安装也从这组命令开始：

```powershell
& $ScaPython -I -B -m simplecadapi.cli init --home $AddonHome --skills-dir $SkillsDir --no-shell
if ($LASTEXITCODE) { throw 'SCA initialization failed' }
& $ScaPython -I -B -m simplecadapi.cli addon add --home $AddonHome --skills-dir $SkillsDir $RepoRoot
if ($LASTEXITCODE) { throw 'add-on registration failed' }
$env:SCA_PHYSICS_BOOTSTRAP_PYTHON = $Python312
& $ScaPython -I -B -m simplecadapi.cli addon use --home $AddonHome --skills-dir $SkillsDir sca-physics provision
if ($LASTEXITCODE) { throw 'add-on provisioning failed' }
& $ScaPython -I -B -m simplecadapi.cli addon check --home $AddonHome --skills-dir $SkillsDir sca-physics
if ($LASTEXITCODE) { throw 'add-on check command failed' }
$Registry = Get-Content -LiteralPath (Join-Path $AddonHome 'registry.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if ($Registry.addons.'sca-physics'.runtime_check.passed -ne $true) { throw 'sca-physics runtime_check did not pass' }
& $ScaPython -I -B -m simplecadapi.cli addon list --home $AddonHome --skills-dir $SkillsDir
if ($LASTEXITCODE) { throw 'add-on listing failed' }
```

不要仅凭exit0认定probe通过，以上独立检查registry中的实际`runtime_check.passed`。隔离验收结束后退出专用PowerShell子进程，不改变现用runtime或全局skill；真实用户安装则会按所选路径登记插件和skill。

底层Python项目可普通安装仓库根或wheel到新venv；这不自动完成SCA/skill登记。runtime执行 `python -I -B -m sca_physics check` 与pip check，核对module origins与版本。runtime.check要求simplecadapi/sca_physics均实际安装在当前venv，不能用PYTHONPATH源码注入伪装正常CLI验收。

直接运行依赖仅simplecadapi>=2.2.5,<2.2.6；build依赖hatchling>=1.27,<2；test extra含pytest/jsonschema。物理插件不导入、不依赖USD插件。当前配套导出器为sca-usd-export==0.1.8rc2，其可选physics extra精确依赖sca-physics==0.1.8rc1；导出器消费最终包内sca_physics数据并调用物理插件的校验代码，纯几何路径无需该依赖。Isaac/PhysX为外部可选backend，不随包分发。

如果只准备独立Python环境，可使用下面的源码安装命令；这与SCA的add-on登记是两个步骤，不使用editable安装：

```powershell
& $Python312 -m venv "$RuntimeRoot/.venv"
$PhysicsPython = "$RuntimeRoot/.venv/Scripts/python.exe"
# 私有/离线SDK发行版由使用者提供2.2.5 wheel或明确的wheelhouse，不改SCA源码。
& $PhysicsPython -I -B -m pip install "$SdkWheel"
& $PhysicsPython -I -B -m pip install "$RepoRoot[test]"
if ($LASTEXITCODE) { throw 'source installation failed' }
& $PhysicsPython -I -B -m pip check
if ($LASTEXITCODE) { throw 'dependency check failed' }
& $PhysicsPython -I -B -m sca_physics check
if ($LASTEXITCODE) { throw 'runtime check failed' }
& $PhysicsPython -I -B -m pytest "$RepoRoot/tests" --basetemp "$NewTestOutput/temp" --junitxml "$NewTestOutput/tests.xml"
```

`$NewTestOutput`必须先创建且位于仓库外。两项需外部真实CAD-FEM包的测试另用 `tests/test_cad_deformable.py --package "$CadFemPackage" --target "$ExactNodeId" -v`；包内有唯一CAD-FEM目标时可省略target。不要把缺少测试依赖导致的跳过当作通过。

更新时从唯一维护源码构建，在新隔离环境验证后再改变正式入口；payload/site-packages/skill都需核对。回退使用已保留旧源码/wheel/注册状态和旧入口，不默认remove旧插件（可能删除runtime）。

使用Schema1.8前先升级导出器并按其说明启用匹配physics依赖，再升级附加物理配置的入口；也可以在新home一次安装上述配套候选。纯几何用户无需同时升级或安装本插件。旧包先只读验证，再另存新输出；不要通过重写schema版本伪装旧导出器支持新字段。完整候选范围见[发布准备](release-candidate.zh-CN.md)。
