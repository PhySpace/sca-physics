# 从 Agent 决策到最终产品包

适用physics0.1.8rc1 / USD0.1.8rc2配套候选。`run_task.py`执行已形成的决策，不自行理解自然语言、联网检索或识别材料。

Agent先读任务描述，判断模型范围，查资料或提出工程假设，然后编写decision JSON。两个JSON示例保存了原自然语言需求及Agent决定：

- `wire.decision.json`：450mm/2.6mm多股PVC软电线，显式选择匹配预设，线质量引用LAPP相似构造名义数据，EI/GJ等由可追溯工程初值补全；N由限定辅助规则计算，不预填历史结果。
- `spring-wire.decision.json`：300mm/1mm直圆弹簧钢丝，参考SCHERDEL EN10270-1 SM的rho/E/G，用公开`circle_rod`得到lambda、EI、GJ；目标间距15mm是该任务的Agent工程选择，程序计算并显式提交N。阻尼0是理想无损假设，不是实物结论。

来源保存在逐值wrapper或本次声明source中。模型只支持圆截面、直线自然态、平面初态、不可伸长近似及逐关节阻尼；这些示例不证明材料标定、伸长、塑性或完整动态分段等价。资料URL及适用条件在各JSON中。

先用配套部署入口安装并检查两个runtime，然后使用真实宿主SCA命令和显式路径：

```powershell
& $HostPython -I -B $TaskScript --decision $DecisionJson `
  --sca-python $HostPython --home $AddonHome --skills-dir $SkillsDir --output $NewOutputDirectory
if ($LASTEXITCODE) { throw 'Task failed; keep its new output and logs' }
```

`$TaskScript`为本目录`run_task.py`，路径不依赖工作区布局。输出目录必须不存在。脚本先正式检查配套安装，再用physics独立Python和SCA公开API创建真实圆柱、赋原生材料并capture。

零件几何以局部中心为原点，使用装配位姿放回需求规定的世界位置；保持世界尺寸和中心线不变，减少 float32 Mesh 的无谓坐标舍入。几何容差不修改；仍不满足容差时导出必须拒绝，不能在失败后增大检查门槛。

建模、声明准备、physics保存、独立读取、USD导出及回读都使用新进程；导出只传最终包及SHA256，不传decision/config或建模变量。输出包含原始/最终包、来源完整的声明、独立期望配置、USD/history/report、命令日志和验证摘要。回读检查身份、原生语义保留、实际质量、N、端点、碰撞及完整声明来源。`simulator_validated=false`保持到单独的真实后端任务检查，不能把静态通过写成仿真通过。

普通刚体的密度继续通过SCA公开Material设置；链的实际质量来自保存的lambda乘材料弧长。CAD等效密度不等于复合线芯的材料本体密度。

在正式身份检查通过后，可用配套 USD runtime 的 Python 执行本目录 `check_controls.py --raw <wire案例的raw.scadpkg> --output <新目录>`，对照来源优先、0/false、缺来源/非法字段/预算拒绝和原生材料密度的实际质量路径。该控制输入限定为 2.6 mm 电线案例，不是任意对象分类器；保存逐项结果及失败前进度，不运行仿真。
