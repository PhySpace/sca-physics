# 从 GitHub Pre-release 安装 sca-physics 0.1.8rc1

源码、文档、技能资源和必要测试在仓库 `main`；安装包由 [v0.1.8rc1 Pre-release](https://github.com/wwlloo/sca-physics/releases/tag/v0.1.8rc1) 的附件分发。下载 **`sca-physics-0.1.8rc1.zip`** 和同页 **`SHA256SUMS.txt`**；GitHub 自动生成的 **Source code (zip/tar.gz)** 是源码快照，不是本指南使用的插件安装包。

这是 rc 候选，非稳定版，不标记 Latest。实际验证配对仅为 **physics 0.1.8rc1 + USD 0.1.8rc2**；配套 [USD Pre-release](https://github.com/PhySpace/sca-usd-export/releases/tag/v0.1.8rc2)。环境为 Windows x86-64、Python3.12.15、SCA SDK2.2.5、OpenUSD26.8、OCP7.9.3.1；其他组合不作保证。GitHub 附件下载及安装的本轮实际结果见对应 Release 正文，不用本地包测试代替下载验收。

physics 只直接依赖 `simplecadapi>=2.2.5,<2.2.6`，负责 capture 后的真实来源声明及保存/重载，不导出 USD、不实现求解器。hatchling 为构建依赖，pytest/jsonschema 为开发测试依赖，Isaac/PhysX 为另备仿真环境。无嵌入物理配置的几何用户只需 USD。

## 下载、核验和解压

先在新的 PowerShell 窗口执行以下设置。示例短根 `C:/sca-rc` 可替换为你有写权限的全新短目录；目录必须尚不存在，不能指向已有安装。安装代码和 runtime 根不能含单引号或 cmd 元字符（`& | < > ^ % ! ( )`）。Windows 未启用长路径时，深目录曾使 Jedi 依赖解包报 WinError206；没有通用最大长度保证。

宿主 Python 必须已合法安装 SCA SDK 2.2.5。独立 runtime 仍需取得其依赖：提供可访问的包索引，或包含 SDK 2.2.5、传递依赖和 hatchling 的可信 wheelhouse。插件 ZIP 不附带 SDK、OCP、OpenUSD 或 Isaac 二进制；仅宿主已装 SDK 不等于 pip 能在新 runtime 取得它。离线安装须自行备齐全部匹配 wheel，不能用跳过依赖来伪装成功。既有本地验证使用明确的离线wheelhouse；在线索引完整性未验证，本次下载包的环境以Release正文为准。

```powershell
$ErrorActionPreference = 'Stop'
$ScaPython = (Read-Host '已安装 SCA 2.2.5 的 python.exe 完整路径').Trim('"')
$Python312 = (Read-Host '基础 Python 3.12.15 的 python.exe 完整路径').Trim('"')
$Root = [IO.Path]::GetFullPath((Read-Host '全新短目录，例如 C:/sca-rc').Trim('"'))
if (Test-Path -LiteralPath $Root) { throw '目录已存在，请选择全新短目录' }
New-Item -ItemType Directory -Path $Root -ErrorAction Stop | Out-Null

# 当前新窗口专用；重定向整条命令链，而非仅 init 一条命令。
# 自定义 home/skills-dir 本身不能阻止 SDK 写真实用户 ~/.sca/config.toml。
Get-ChildItem Env: | Where-Object { $_.Name -like 'SCA_*' } | Remove-Item
$ProfileDir = Join-Path $Root 'u'
New-Item -ItemType Directory -Path $ProfileDir -ErrorAction Stop | Out-Null
$env:USERPROFILE = $ProfileDir
$env:HOME = $ProfileDir
$env:APPDATA = Join-Path $ProfileDir 'AppData/Roaming'
$env:LOCALAPPDATA = Join-Path $ProfileDir 'AppData/Local'
New-Item -ItemType Directory -Path $env:APPDATA, $env:LOCALAPPDATA | Out-Null
& $ScaPython -I -B -c 'import sys; from pathlib import Path; assert Path.home().resolve() == Path(sys.argv[1]).resolve(); print(Path.home())' $ProfileDir
if ($LASTEXITCODE) { throw '专用用户配置目录校验失败' }
$AddonHome = Join-Path $Root 'a'
$SkillsDir = Join-Path $Root 's'
$env:SCA_PHYSICS_BOOTSTRAP_PYTHON = $Python312
$env:SCA_USD_BOOTSTRAP_PYTHON = $Python312
# 可选：只能填写自己合法取得的依赖目录；不固定个人机器路径。
# $DependencyWheels = (Resolve-Path (Read-Host '可信 wheelhouse 完整路径')).Path
# $env:SCA_ADDON_WHEELHOUSE = $DependencyWheels
# 完全离线且依赖齐全时再设置 $env:PIP_NO_INDEX = '1'。

function Get-AddonRelease([string]$Repository, [string]$Tag, [string]$Name, [string]$Version) {
    $Folder = Join-Path $Root "download/$Name"
    New-Item -ItemType Directory -Path $Folder -ErrorAction Stop | Out-Null
    $Filename = "$Name-$Version.zip"
    $Zip = Join-Path $Folder $Filename
    $Sums = Join-Path $Folder 'SHA256SUMS.txt'
    $Url = "https://github.com/$Repository/releases/download/$Tag"
    Invoke-WebRequest -Uri "$Url/$Filename" -OutFile $Zip
    Invoke-WebRequest -Uri "$Url/SHA256SUMS.txt" -OutFile $Sums
    $Pattern = '^([0-9a-fA-F]{64})\s+\*?' + [regex]::Escape($Filename) + '$'
    $Entries = @(Get-Content -LiteralPath $Sums -Encoding UTF8 | Where-Object { $_ -match $Pattern })
    if ($Entries.Count -ne 1) { throw '校验文件没有唯一、准确的 ZIP 文件名记录' }
    $Expected = ([regex]::Match($Entries[0], $Pattern)).Groups[1].Value
    $Actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $Zip).Hash
    if ($Actual -ne $Expected) { throw "SHA256 不匹配：$Filename" }
    Write-Host "$Filename SHA256 $Actual"
    $Extracted = Join-Path $Root 'src'
    Expand-Archive -LiteralPath $Zip -DestinationPath $Extracted -ErrorAction Stop
    $Source = Join-Path $Extracted $Name
    if (-not (Test-Path -LiteralPath (Join-Path $Source 'sca-addon.toml'))) { throw '解压布局缺少插件根清单' }
    return $Source
}

function Assert-AddonReady([string]$Name) {
    & $ScaPython -I -B -m simplecadapi.cli addon check --home $AddonHome --skills-dir $SkillsDir $Name
    if ($LASTEXITCODE) { throw "$Name check 命令失败" }
    $Registry = Get-Content -LiteralPath (Join-Path $AddonHome 'registry.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($Registry.addons.$Name.runtime_check.passed -ne $true) { throw "$Name runtime_check 未通过" }
}
```

这些命令写入所选专用 profile、home、skill 和相邻 runtime，不修改已存在的稳定入口。完成后退出该 PowerShell 窗口；不要将专用 profile 变量写入全局环境。普通用户若要注册到自己的现用配置，应另行明确选择其安装位置；本指南默认使用独立新位置。

## 用 SCA 官方机制安装并检查

同一 PowerShell 窗口继续执行。SDK2.2.5 接受**解压后含 `sca-addon.toml` 的目录**，不是 ZIP 路径；目录名须保持 `sca-physics`。

```powershell
$PhysicsSource = Get-AddonRelease 'wwlloo/sca-physics' 'v0.1.8rc1' 'sca-physics' '0.1.8rc1'
& $ScaPython -I -B -m simplecadapi.cli init --home $AddonHome --skills-dir $SkillsDir --no-shell
if ($LASTEXITCODE) { throw 'SCA init 失败' }
& $ScaPython -I -B -m simplecadapi.cli addon add --home $AddonHome --skills-dir $SkillsDir $PhysicsSource
if ($LASTEXITCODE) { throw 'physics add 失败' }
& $ScaPython -I -B -m simplecadapi.cli addon use --home $AddonHome --skills-dir $SkillsDir sca-physics provision
if ($LASTEXITCODE) { throw 'physics provision 失败' }
Assert-AddonReady 'sca-physics'
$PhysicsPayload = Join-Path $AddonHome 'sca-physics'
$PhysicsPython = Join-Path $Root 'runtimes/sca-physics/.venv/Scripts/python.exe'
& $PhysicsPython -I -B -c 'import sca_physics; print(sca_physics.__version__); print(sca_physics.__file__)'
if ($LASTEXITCODE) { throw 'physics 模块加载失败' }
```

`addon add` 时 runtime 尚未准备，其检查警告不能当作失败后跳过 provision 的理由；同样不能只以 `addon check` 退出0当作 probe 通过，须检查上面的真实 registry 字段。实际模块应来自本次 `runtimes/sca-physics/.venv/Lib/site-packages`，不是源码目录、稳定安装或全局 skill。

## 最小来源迁移与保存/重载

下面使用随包真实软件 fixture，输出始终为新文件。`collision_enabled=false` 的来源明确是试验估计，不能复制后冒称真实设备测量或用户要求。

```powershell
$Out = Join-Path $Root 'out'
New-Item -ItemType Directory -Path $Out -ErrorAction Stop | Out-Null
$Raw = Join-Path $PhysicsPayload 'verification/raw.scadpkg'
$Config = Join-Path $PhysicsPayload 'examples/pendulum/physics-input.json'
$Final = Join-Path $Out 'final.scadpkg'
& $PhysicsPython -I -B -m sca_physics enrich $Raw --config $Config --output $Final
if ($LASTEXITCODE) { throw 'enrich 失败' }
& $PhysicsPython -I -B -m sca_physics validate $Final
if ($LASTEXITCODE) { throw '重新读取物理包失败' }
```

需要 USD 导出时，按 [USD 下载与安装指南](https://github.com/PhySpace/sca-usd-export/blob/v0.1.8rc2/docs/release-installation.zh-CN.md) 准备配套读取端及其准确 physics 依赖，通过 provision/check 后再切换实际产品的物理写入入口。可在全新 home 一次准备整组；不要只升级写入端便假定旧读取端认识schema1.8。已有准确 physics0.1.8rc1 者无需重复升级，但若 payload 文件改变，仍需重新 provision/check；版本号相同不代表文件相同。

## 兼容、升级和限制

**旧无来源裸参数原样不兼容；按要求补充来源信息后，所测试案例通过。**保留原值、单位与schema，补真实 `source.kind/detail`，资料引用还需真实 citation/conditions。来源可位于字段、组或声明根；缺来源不能批量伪称explicit。[随包迁移输入](../examples/pendulum/physics-input.json)和上面的命令可以运行，完整范围见[兼容与升级](release-candidate.zh-CN.md)。

所测旧包仅为2026-10-19 physics0.1.0/schema1.0摆臂包与2026-10-20 physics0.1.3rc1/schema1.1机械包，均通过读取、SDK原生重载、物理快照保持和USD导出；旧路径/内存 `export_package` 与所测ExportConfig/CLI有效。确切输入与SHA256见[候选兼容表](release-candidate.zh-CN.md#兼容性合同及迁移)，不扩大为所有历史版本。

更新既有安装时保留原环境和原包，先按官方 `addon update` 更新来源payload，再重新provision/check；不要直接复制源码到site-packages或skill，也不要默认remove旧插件。USD物理路径直接调用physics合同/几何模块；缺peer、错版本和未知schema有明确拒绝，不应靠降低schema标签绕过。

**未验证：两项外部CAD-FEM检查、Isaac／PhysX行为、其他环境、全部历史版本组合及全部旧参数分支。**仍有既有FEM/链精度、自然态和接触表示限制。安装、保存、重载和静态USD通过不代表物理仿真、工程精度或全部Isaac属性通过。
