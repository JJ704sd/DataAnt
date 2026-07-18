# 商品采集与输出流水线重构设计

## 文档信息

- 日期：2026-07-18
- 提案索引：`[Index: #20260718-01]`
- 基线提交：`2265064 fix: harden product output performance controls`
- 适用范围：`web-scraping.dev` 商品采集结果到 Excel、JSON、HTML 三件套的本地输出链路
- 设计状态：已批准架构方向，等待文档复核

## 1. 背景

当前商品链路已经形成完整闭环：

```text
WebScrapingDevAdapter
  -> ProductRunner
  -> ProductCollection
  -> ProductOutputBundle
  -> products.xlsx / products.json / gallery.html
```

现有实现具备受控联网门禁、最多 10 件商品、固定访问间隔、阻断即停、离线 fixture、三产物并发生成、目录级原子提交、失败恢复和输出一致性校验。基线全量离线测试为 273 项，全部通过。

本轮不是功能扩展，而是行为保持型重构。目标是让输出链路的职责、接口和失败边界可以独立理解与测试，同时保留现有 CLI、Schema、安全约束和用户可观察行为。

## 2. 审查结论

### 2.1 `ProductOutputBundle` 职责过多

当前 `app/product_output_bundle.py` 同时负责：

- 进程内目标目录锁；
- 跨进程文件锁；
- Windows/Linux 锁实现；
- 陈旧 staging/backup 清理；
- 历史 Excel 读取与商品合并；
- bundle 数量上限校验；
- 输出快照构建；
- 三 writer 并发调度；
- staging 产物一致性校验；
- 目标目录备份、替换和失败恢复；
- 性能计时和回执构造。

这些职责具有不同的变化原因。锁与目录事务关注文件系统安全，writer 调度关注产物生成，快照关注数据一致性，bundle 门面则只应编排流程。继续集中在一个模块中会增加回归定位难度。

### 2.2 快照只有表面不可变性

`ProductOutputSnapshot` 使用 `frozen=True`，但其 `payload` 是可变字典，`product_rows` 中的元素也是可变字典。三个 writer 当前只读这些对象，因此尚未出现可见错误；但类型契约不能阻止 writer 或未来维护代码在并发执行时修改共享数据。

本轮需要把“同一份不可变快照”从文档约定提升为可测试的代码契约。

### 2.3 回执接口被 CLI 防御性读取削弱

`app/main.py` 使用多个 `getattr(receipt, field, default)` 读取输出指标。这能兼容历史测试替身，但也会让真实回执字段被误删或改名时静默降级为零值，使接口漂移无法尽早暴露。

输出回执应提供稳定的显式字段；测试替身应遵守同一协议，而不是由生产 CLI 猜测字段是否存在。

### 2.4 Excel 输出存在局部类型与冗余问题

`ProductExcel._workbook_for()` 的返回标注与实际二元组不一致；`_row_for()` 已不在主路径使用。两者不会改变当前运行结果，但降低了静态可读性，应在不改变工作簿契约的前提下修正。

### 2.5 不纳入本轮的问题

`app/product_gallery.py` 和 `app/sites/web_scraping_dev.py` 文件较大，但分别承载自包含静态模板和站点解析规则。拆分它们会扩大变更面，并引入与本轮输出事务边界无关的风险，因此明确延期。

## 3. 目标

1. 将快照、产物写入、产物验证和原子提交拆成边界清晰的组件。
2. 保留 `ProductOutputBundle.write(collection)` 作为稳定公开入口。
3. 让 Excel、JSON、HTML 始终消费同一份只读、顺序稳定的输出快照。
4. 让锁、staging、backup、replace 和 rollback 只存在于目录事务组件中。
5. 让三 writer 的并发上限固定为 3，且单 writer 失败时不提交任何新 bundle。
6. 用明确回执替代 CLI 中的字段猜测。
7. 保持所有既有外部行为和安全边界不变。

## 4. 非目标

本轮不包含：

- 修改 `WebScrapingDevAdapter` 的页面解析器或 URL 白名单；
- 修改 `ProductRunner` 的发现、重试、节流或阻断策略；
- 修改真实联网规则、并发访问模型或浏览器行为；
- 重写或拆分静态画廊模板；
- 修改商品字段、Excel 列顺序、JSON `schema_version` 或 HTML 交互；
- 修改豆瓣电影流程；
- 引入数据库、消息队列、异步框架或第三方并发库；
- 提升真实联网批次上限；
- 把运行产物加入 Git。

## 5. 必须保持的外部契约

### 5.1 CLI 与安全

- 子命令仍为 `collect-products`。
- 必须显式传入 `--live-approved`。
- `--max-products` 仍为 1 到 10。
- 必须使用 headed 浏览器。
- `--min-interval` 不得低于 2 秒。
- 只允许 `/products`、合法商品分页和 `/product/<digits>`。
- 429、阻断、登录/安全检查、挑战页、站外跳转或禁止路径必须立即停止。
- 不自动登录、不解 CAPTCHA、不求解 challenge、不绕过保护。

### 5.2 输出

- 目标目录内仍生成 `products.xlsx`、`products.json`、`gallery.html`。
- Excel 工作表名、15 列名称、顺序和值类型保持不变。
- JSON 保持 `schema_version=1`、UTF-8、compact separators 和现有字段结构。
- HTML 内容和交互行为保持不变。
- 商品顺序保持“历史首次出现顺序 + 本次 upsert 更新原位置 + 新商品追加”的现有语义。
- 合并后仍不得超过 10 件商品。

### 5.3 失败与退出码

- 输出目录或文件被占用仍映射为 `OutputLockedError`，CLI 退出码为 4。
- 未分类输出异常仍由 CLI 映射为退出码 5。
- 旧 bundle 在新 bundle 提交失败时必须可恢复。
- writer 或验证失败时不得暴露部分新 bundle。

## 6. 目标架构

```text
ProductCollection
  -> ProductOutputSnapshotBuilder
  -> ProductOutputSnapshot
  -> ProductArtifactWriters
       -> products.xlsx
       -> products.json
       -> gallery.html
  -> ProductBundleVerifier
  -> AtomicBundleCommitter
       -> lock
       -> staging
       -> backup
       -> replace / rollback
```

`ProductOutputBundle` 作为门面串联上述步骤：

```text
加锁
  -> 合并历史记录
  -> 校验 10 件上限
  -> 构建一次快照
  -> 创建 staging
  -> 并发写三产物
  -> 校验 staging
  -> 原子提交
  -> 返回强类型回执
```

## 7. 组件与文件边界

### 7.1 `app/product_output_snapshot.py`

职责：

- 从 `ProductCollection` 构建一次规范化 payload；
- 固化商品顺序和 `product_id` 顺序；
- 生成 JSON 文本；
- 提供 Excel 与画廊所需的只读行数据；
- 保证 writer 无法修改共享快照。

从现有 `app/product_json.py` 迁入 `product_payload()`、`ProductOutputSnapshot` 和
`build_product_output_snapshot()`。`product_json.py` 保留
`render_product_json()`，并兼容性重导出上述三个现有名称，避免破坏当前导入方。
依赖方向固定为 `product_json -> product_output_snapshot -> product_models`，
`product_output_snapshot` 不反向导入 `product_json`。

快照字段：

```text
payload        只读映射
product_rows   只读映射元组
json_text      UTF-8 文本
product_ids    字符串元组
```

不可变策略使用标准库只读映射包装和元组，不引入第三方 immutable collection。
builder 先以局部普通字典完成 payload 和 JSON 文本序列化，再递归冻结映射和序列；
不得把 `MappingProxyType` 直接传给 `json.dumps()`。若画廊渲染需要普通字典，
只能在渲染边界创建局部副本，不能修改共享快照。

### 7.2 `app/product_artifact_writers.py`

职责：

- 接收 `ProductCollection`、只读快照和 staging 目录；
- 用固定 3 个 worker 并发写 Excel、JSON、HTML；
- 收集每个 writer 的字节数和耗时；
- 任一 writer 失败时取消尚未开始的任务，并等待已启动任务结束；
- 返回 `ArtifactWriteReceipt`。

该组件不负责：

- 合并历史记录；
- 创建或交换目标目录；
- 清理陈旧目录；
- 映射 CLI 退出码。

线程只并发执行本地输出，不允许触及浏览器、适配器或网络。

### 7.3 `app/product_bundle_transaction.py`

职责：

- 提供目标目录的进程内锁和跨进程文件锁；
- 创建唯一 staging/backup sibling；
- 清理超过 24 小时且严格符合本项目命名规则的陈旧 sibling；
- 提交 staging；
- 在第二次 rename 失败时恢复 backup；
- 在退出路径清理本轮 staging；
- 将目录占用和不可恢复提交错误转换为 `OutputLockedError`。

事务对象只处理目录，不理解商品、JSON、Excel 或 HTML。

跨平台语义保持现状：Windows 使用 `msvcrt` 非阻塞轮询并保留 30 秒上限；Linux 使用 `fcntl.flock`。Linux 路径不新增超时行为，以避免本轮引入平台语义变化。

### 7.4 `app/product_output_bundle.py`

重构后保留：

- `ProductOutputBundle`；
- `BundleWriteReceipt`；
- `BUNDLE_LIMIT`；
- 现有 `write()` 和 `read_product_ids()` 公共接口。

该模块只负责编排：

1. 在事务锁内读取并合并历史记录；
2. 校验 bundle 上限；
3. 构建合并后的 `ProductCollection`；
4. 构建快照；
5. 调用 writer；
6. 调用 verifier；
7. 调用事务提交；
8. 汇总回执。

### 7.5 `app/product_bundle_verifier.py`

职责：

- 校验 Excel 回执中的 ID 与快照 ID 完全一致；
- 从 staging JSON 读取 ID 并与快照比较；
- 校验三件套文件全部存在且是普通文件；
- 返回验证耗时或成功标记。

本轮保留现有验证深度，不新增 HTML DOM 解析或 Excel 二次全量读取，以免把验证成本和行为范围扩大。

### 7.6 `app/main.py`

CLI 仍负责：

- 联网门禁和路径验证；
- 启动浏览器及运行器；
- 调用 `ProductOutputBundle.write()`；
- 将结构化指标写入日志；
- 映射退出码。

CLI 改为直接读取 `BundleWriteReceipt` 的必备字段。生产回执字段缺失应在测试或开发时立即失败，不再静默回退为零值。测试替身必须返回完整回执。

### 7.7 `app/product_excel.py`

- 修正 `_workbook_for()` 的返回类型；
- 删除无调用方的 `_row_for()`；
- 保持 `write()`、`read()`、`merge_existing()` 和 `PRODUCT_COLUMNS` 行为不变。

## 8. 数据流与不可变性

1. `ProductRunner` 返回不可变 `ProductCollection`。
2. bundle 在锁内读取历史 Excel 并执行 upsert。
3. 合并记录生成新的 `ProductCollection`，原输入不被修改。
4. snapshot builder 对每条记录只调用一次 `to_primitive()`。
5. builder 固化只读 payload、行序列、JSON 文本和 ID 序列。
6. Excel writer 读取行序列；JSON writer 直接写 `json_text`；gallery writer 读取同一快照。
7. writer 不得重新调用 `ProductRecord.to_primitive()`。
8. verifier 以 snapshot 的 `product_ids` 为唯一预期顺序。
9. 只有验证通过的 staging 才能进入提交阶段。

## 9. 并发与资源边界

- 本地 writer 数固定为 3，不根据 CPU 数动态扩大。
- 三个任务分别对应 Excel、JSON、HTML；不拆分单个产物内部工作。
- `ProductCollection` 和 snapshot 在 writer 生命周期内只读。
- `ThreadPoolExecutor` 必须在成功和异常路径关闭。
- 异常路径使用 `cancel_futures=True`，同时等待已运行任务结束，避免 staging 清理与 writer 竞争。
- 对同一目标目录的“读取旧值 + 合并 + 写入 + 交换”保持在同一目标锁临界区内。
- 不改变浏览器单 tab 串行访问模型。

## 10. 原子提交与恢复

### 10.1 首次写入

```text
创建 staging
  -> 写三件套
  -> 验证
  -> staging rename 为 target
```

提交前 target 不存在；任何前置失败只清理 staging。

### 10.2 覆盖已有 bundle

```text
target rename 为 backup
  -> staging rename 为 target
  -> 删除 backup
```

### 10.3 第二次 rename 失败

```text
若 backup 存在且 target 不存在
  -> backup rename 回 target
  -> 抛 OutputLockedError
```

如果恢复也失败，异常信息必须明确指出旧 bundle 未能恢复，并保留原始异常链。不得把该情况报告为普通验证失败。

### 10.4 清理规则

- 本轮 staging 在 `finally` 中清理。
- 仅删除目标目录同级、超过 24 小时且名称严格匹配 `.{target}.staging-*` 或 `.{target}.backup-*` 的目录。
- 不删除 target、`.venv`、`.worktrees`、`outputs` 根目录或其它隐藏目录。
- 锁文件不包含敏感信息，不纳入 bundle，也不提交 Git。

## 11. 错误处理

| 失败点 | 对外异常/行为 | 是否提交新 bundle |
| --- | --- | --- |
| 历史 Excel Schema 非法 | `ValueError`，CLI 退出 5 | 否 |
| 合并后超过 10 件 | `ValueError`，CLI 退出 5 | 否 |
| 快照构建失败 | 原异常，CLI 退出 5 | 否 |
| 任一 writer 失败 | 原异常，CLI 退出 5 | 否 |
| staging 一致性失败 | `ValueError`，CLI 退出 5 | 否 |
| 目标目录被占用 | `OutputLockedError`，CLI 退出 4 | 否，恢复旧 bundle |
| 旧 bundle 恢复失败 | `OutputLockedError`，CLI 退出 4 | 否，错误信息明确恢复失败 |
| 陈旧目录清理失败 | 原 `OSError`，CLI 退出 5 | 否 |

输出层不捕获或转换商品采集状态；`BLOCKED`、`PAGE_CHANGED` 等仍由运行器和 CLI 按既有流程处理。

## 12. 回执契约

`BundleWriteReceipt` 保持现有字段名称，并将其视为必备字段：

```text
product_ids
excel
bytes_by_file
payload_build_ms
json_write_ms
gallery_write_ms
excel_write_ms
verify_ms
total_local_ms
```

约束：

- `product_ids` 与三件套中的商品顺序一致；
- `bytes_by_file` 必须且只包含三个标准文件名；
- 时间字段使用毫秒、非负浮点数；
- `total_local_ms` 覆盖快照、写入、验证和提交阶段；
- CLI 不再从磁盘回读字节数作为正常回退路径。

## 13. 测试设计

实施必须遵循 TDD，先用测试固定现有行为，再拆分实现。

### 13.1 快照测试

- 每条记录只调用一次 `to_primitive()`；
- 商品顺序和 ID 顺序稳定；
- JSON 文本与当前 Schema 完全兼容；
- writer 无法修改 payload 或行映射；
- 金额、状态和时间序列化保持现状。

### 13.2 writer 测试

- 固定创建 3 个 writer 任务；
- 三件套消费同一个 snapshot；
- 三个回执包含正确字节数、ID 和非负耗时；
- 任一 writer 失败时异常向上传播；
- executor 在异常路径关闭；
- writer 不访问网络、不创建浏览器。

### 13.3 verifier 测试

- Excel ID 不一致时失败；
- JSON ID 缺失、重复、乱序时失败；
- 任一标准文件缺失时失败；
- 一致时不修改 staging 内容。

### 13.4 事务测试

- 首次提交成功；
- 覆盖提交成功并删除 backup；
- 第二次 rename 失败时恢复旧目录；
- 恢复失败时抛带明确信息的 `OutputLockedError`；
- 同一目标的并发写不会丢失更新；
- 不同目标可以独立写入；
- 仅清理严格匹配且超龄的 sibling；
- 活跃 staging、无关目录和 `.gitkeep` 不被删除；
- Windows 文件锁超时维持 30 秒语义。

### 13.5 bundle 门面测试

- 历史 upsert 顺序保持现状；
- 合并后超过 10 件立即失败；
- snapshot 只构建一次；
- 只有验证成功后才调用提交；
- 回执指标完整传回 CLI。

### 13.6 CLI 回归测试

- CLI 直接读取完整回执；
- 指标日志字段和数值保持现状；
- `OutputLockedError` 仍返回 4；
- 其它输出异常仍返回 5；
- 浏览器创建前的所有 live gate 保持不变。

### 13.7 全量验证

- 全量 `pytest -q`；
- `scripts.verify_core` 覆盖率与离线门禁；
- `scripts.verify_products` 三产物验证；
- `scripts.benchmark_products` 离线基准；
- `python -m pip check`；
- `git diff --check`；
- tracked runtime artifact / secret scan。

所有验证均离线执行，不传 `--live-approved`，不启动真实浏览器，不访问 `web-scraping.dev` 或豆瓣。

## 14. 兼容与迁移策略

采用渐进迁移，避免一次性替换全部实现：

1. 先为现有行为补充边界测试；
2. 提取不可变 snapshot，保留原 JSON 公共入口；
3. 提取 writer 调度，保持原回执字段；
4. 提取 verifier；
5. 提取目录事务；
6. 将 `ProductOutputBundle` 收敛为门面；
7. 更新 CLI 测试替身并移除生产 `getattr` 回退；
8. 清理 Excel 类型和死代码；
9. 跑全量离线门禁和 benchmark 对比。

每一步都必须保持测试绿色，并形成可独立审查的提交。若性能基准出现明显退化，应先定位本地输出阶段原因，不得通过降低网络间隔或减少一致性验证来换取绿色指标。

## 15. 验收标准

- `ProductOutputBundle.write()` 的调用方式不变。
- 输出文件名、Excel 15 列、JSON Schema 和 HTML 行为不变。
- 三件套由同一份不可变 snapshot 生成。
- `product_output_bundle.py` 不再包含平台文件锁实现、writer 线程调度和 staging JSON 验证细节。
- 锁、writer、verifier、snapshot 均能独立单元测试。
- 单 writer 或验证失败不会提交部分 bundle。
- 覆盖提交失败会恢复旧 bundle，并保持退出码 4。
- CLI 不再使用 `getattr` 猜测回执字段。
- 商品数量上限、访问间隔、headed 要求、URL 白名单和阻断即停规则保持不变。
- 全量离线测试、核心验证、商品验证、依赖检查和 diff 检查通过。
- CI 与本地自动验证不访问真实网站。
- `outputs/`、`browser-profile/`、`artifacts/` 中仍只有 `.gitkeep` 可被 Git 跟踪。

## 16. 风险与控制

| 风险 | 控制措施 |
| --- | --- |
| 模块拆分造成循环导入 | snapshot、writer、verifier、transaction 只向领域模型和底层 writer 单向依赖 |
| 只读映射与现有画廊代码不兼容 | 在画廊边界做局部普通对象转换，并用 HTML 快照测试固定输出 |
| 事务提取改变恢复时机 | 先用 rename 失败测试固定现有顺序，再移动实现 |
| 并发异常被吞掉 | 所有 future 显式取结果，首个失败向上传播，executor 始终关闭 |
| CLI 指标测试替身不完整 | 测试统一构造正式 `BundleWriteReceipt` |
| 过度扩展到站点或 UI | 非目标明确排除 adapter、runner 网络策略和 gallery 模板重写 |

## 17. 后续工作

本文档批准后，下一步是生成逐任务实施计划。实施计划必须为每个组件提供测试先行步骤、精确文件路径、预期失败、最小实现、验证命令和独立提交点。

站点适配器拆分、画廊模板模块化以及更通用的多站点输出接口应分别设计，不与本轮重构合并。
