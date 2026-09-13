# v31 发布与复现

本次将最好单次成绩的capture-v31作为master默认方案。源代码的17个导出模块与已评分包manifest记录逐字节一致；`agent.py`、`vision.pt`和`evaluation.json`保持原字节。训练数据仍为appearance-v3的已审核数据，本轮没有重训。

## 原始结果

seed101，600秒请求/599.9833秒记录；28.33分、4份报告、RMSE6.5412米、0/3捕获、0惩罚、passed=false。未完成20秒双机捕获，也未证明多seed稳定提升。后续候选未超过它，故本次发布v31。

## 运行

先按[QUICKSTART](QUICKSTART.md)准备官方Windows UE环境和Git LFS资产。在ZqhjGame根目录PowerShell运行：

```powershell
$runDir = "artifacts/vision/runs/v31-$(Get-Date -Format yyyyMMdd-HHmmss)-seed104"
.\vision.cmd run --ue-direct --duration 600 --seed 104 `
  --submission artifacts/submission/capture-v31/agent.py `
  --enable-reports --max-photos 400 --output $runDir
```

seed104仅为复测示例，不能承诺28.33分。以新目录official/*.evaluation.json为准。

## 本次同步范围

- v31的17模块源码与自包含提交包、固定模型、原始评分、发布说明和manifest。
- 适用的身份连续性、相机视场、跨机一致性、接近/圆弧控制测试，以及外围记录和分析工具。
- 安装、训练、重导出、当前问题和交接文档。原v22/v26与已跟踪训练资产保留。
- 原始v31完整照片和后续失败候选仍在开发机，本次不作为运行依赖上传。包内evaluation.json是已评分原始结果的字节一致副本。

## 方法与局限

v31使用人工轮廓候选、局部CNN、图像几何、任务状态机和解析固定翼规划。圆弧修改让规划目标符合近圈曲率；尚未解决首次确认不稳、发现机失视、接应独立确认不足和发现偏晚。不启用Nano，也没有完成YOPO端到端训练。

本次没有调整仿真步频、系统定时器或GPU环境。包内文档和manifest发布字段经过更新，原历史说明在本机归档；代码、模型和评分哈希仍可核验。

## 发布验证

17个源码模块哈希全部一致；重新导出的Agent与原评分包逐字节一致；242项测试通过（206项算法与诊断、36项基础测试）。独立包以三份私有模型处理公开照片及合成SDK观测，在回调禁用Python文件访问时通过，未导入项目源码模块。官方60个审计文件哈希无变化。

证据：[验证清单](../artifacts/checks/release-v31/validation.json)、[测试记录](../artifacts/checks/release-v31/tests.log)、[独立包检查](../artifacts/checks/release-v31/isolated-package.json)。这些检查验证发布完整性，不能替代正式比赛评分或证明已经捕获目标。
