# 豆瓣电影浏览器 Demo 最小修复设计

## 目标

以最小改动恢复现有流程：程序在有头浏览器中提交电影查询，解析搜索结果和详情页，并通过现有 `ExcelStore` 直接写入 `.xlsx` 文件。不引入 Excel 桌面 GUI 自动化，也不重构现有 Runner、匹配器或输出格式。

## 已确认问题

当前 `DoubanMovieAdapter` 假定搜索结果使用旧版 `.result-list` 和 `<div class="result">` 结构。交接证据表明真实搜索页已经改为 React 渲染；现有 `search_results.html` 仍是旧版 fixture，因此离线测试能够通过，却无法覆盖真实页面改版。

真实联网验收还受项目合规门禁约束：必须取得非空、可追溯的 `approval_reference`，才能访问豆瓣、抓取脱敏 fixture 或执行受控 demo。用户口头授权不代替该审批记录。

## 方案

保留 DrissionPage、Runner、匹配器和 Excel 写入链路，只修改搜索页适配层及其离线契约：

1. 为新版 React 搜索结果增加最小、稳定的结果就绪标记，同时保留必要的旧版兼容。
2. 将搜索结果解析收敛在 `DoubanMovieAdapter.parse_search_html()`，兼容新版结果卡片中的详情链接、标题、年份和类型。
3. 空结果、站点拦截和未知页面结构继续映射到现有状态，不新增状态枚举。
4. 详情页解析和 Excel 输出保持不变；只有证据显示详情页也已变化时，才追加相应的最小修复。

## 组件与数据流

`app.main` 读取 CSV 并创建浏览器会话，`Runner` 逐条调用 `DoubanMovieAdapter.search()`。搜索方法提交查询后等待“新版结果、旧版结果或空结果”之一出现，再把当前 HTML 交给纯函数解析。`matcher` 选择候选项后，适配器打开详情页并返回 `MovieResult`，最后由 `ExcelStore` upsert 到目标工作簿。

此设计不使用系统剪贴板，不打开 Excel 桌面窗口，也不改变当前断点续跑和失败诊断行为。

## 错误处理

- 导航失败继续抛出 `NetworkError`，由 Runner 按现有策略重试。
- 检测到验证码、频率限制或拦截文本时继续抛出 `BlockedError`，停止批次。
- 等待超时或页面中既没有可识别结果也没有明确空结果时抛出 `PageChangedError`，避免把页面改版误报为 `NOT_FOUND`。
- 合法空结果返回空候选列表，由 Runner 写入 `NOT_FOUND`。
- Excel 被占用、输入错误和未预期异常沿用现有退出码。

## 测试与验收

实施遵循测试先行：先加入能够复现新版 DOM 的脱敏离线 fixture 和失败测试，确认旧解析器失败；随后实现最小兼容并运行解析器测试、全量 pytest、核心覆盖率门禁和离线 browser smoke。

最终联网验收仅在取得真实 `approval_reference` 后执行：使用批准的少量查询、有头浏览器、至少 5 秒间隔和隔离 profile 运行；检查生成工作簿的列、行数、状态及示例数据，并保存门禁要求的受控 evidence。任何 cookie、会话、截图、HTML、日志和工作簿都保持在已忽略的运行目录中，不提交到 Git。

## 非目标

- 不自动操作 Excel 桌面应用。
- 不绕过验证码、频率限制或站点保护。
- 不伪造审批 evidence 或补写工作簿数据绕过门禁。
- 不修改 CI、Core 13 门禁文档、输入样例或既有输出 schema。
- 不进行与 demo 跑通无关的重构。
