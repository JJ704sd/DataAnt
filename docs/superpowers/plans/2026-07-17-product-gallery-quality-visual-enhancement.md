# 商品画廊数据质量可视化增强实施计划

> For agentic workers: REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax: - [ ].

**Goal:** 在不改变商品采集、领域模型和 products.json schema 的前提下，增强离线商品画廊的数据质量摘要、PARTIAL 原因表达、未分类筛选、证据侧栏、时间格式、响应式布局和可访问性。

**Architecture:** 继续以 ProductCollection 生成的同一份内嵌 product_payload 为唯一数据来源。Python 渲染层负责首次绘制所需的质量摘要占位值和本地化时间文本；页面初始化后的原生 JavaScript 从内嵌 products 数组重新计算可见记录统计、缺失字段聚合和筛选选项，使筛选结果与顶部摘要同步。所有交互仍是单个自包含 HTML 文件中的 CSS 和 JavaScript，不增加网络请求或第二份持久化数据。

**Tech Stack:** Python 3.11、dataclasses 现有 ProductCollection/ProductRecord、原生 HTML/CSS/JavaScript、pytest、现有 scripts.verify_products 离线 bundle verifier。

---

## 前提、范围和不变量

- 批准设计稿：
  docs/superpowers/specs/2026-07-17-product-gallery-quality-visual-enhancement-design.md
- 当前相关基线：app/product_gallery.py 已能生成自包含 gallery.html；tests/test_product_gallery.py 当前 3 项测试全部通过。
- 本轮只处理一个子系统：静态商品画廊的数据质量表达，不拆分为独立分析图表计划。
- ProductStatus、ProductCollection、ProductRecord、products.json 顶层结构和商品 Excel 列契约保持不变。
- 不修改 app/product_models.py、app/product_json.py、app/product_output_bundle.py、采集器、浏览器访问规则、live 授权门禁或 CI 网络边界。
- 质量字段固定按现有解析器的可选字段处理：category、description、primary_image_url（界面显示为 image）、brand。只对 PARTIAL 记录统计这些字段的缺失，避免失败记录因为没有详情字段而污染“缺失字段”摘要。
- 空分类的判定为 null、undefined、空字符串或 trim() 后为空白；非空 category 保留原始值作为分组值，不推断或写回任何分类。
- 状态统计规则与 ProductCollection.from_records 保持一致：SUCCESS 计入 success，PARTIAL 计入 partial，其余状态计入 failed。
- 筛选后顶部卡片展示当前可见记录的统计，summary-context 同时展示当前可见数和内嵌快照的原始总数。
- 生成时间和采集时间只格式化显示，不改写内嵌 JSON 中的原始 ISO 8601 值。
- 不生成、复制或提交 outputs/、artifacts/、browser-profile/ 中的运行时产物；人工验收只使用已有真实产物或测试临时目录。
- 当前工作区已有的无关未跟踪项（例如 .codex-tmp/、.planning/、browser_bot_demo.egg-info/）属于用户环境，执行时不得加入暂存区。

## 文件结构

### 修改

- app/product_gallery.py
  - 增加本地化时间格式化和首次绘制质量占位值；
  - 扩展 _TEMPLATE 的摘要卡、筛选、卡片状态原因、证据侧栏、CSS 和原生 JavaScript；
  - 保持 product_payload(collection) 的嵌入方式和 HTML escaping 逻辑不变。
- tests/test_product_gallery.py
  - 增加包含 SUCCESS、PARTIAL、空白 category 和失败记录的离线测试数据；
  - 先补质量摘要、缺失字段、未分类、时间和离线依赖测试，再验证实现；
  - 保留现有 XSS escaping 和自包含 HTML 测试。

### 不修改

- app/product_models.py
- app/product_json.py
- app/product_output_bundle.py
- scripts/verify_products.py
- tests/test_project_config.py
- 采集器、浏览器会话和 live-run 相关文件

### 本计划文档

- 新建：docs/superpowers/plans/2026-07-17-product-gallery-quality-visual-enhancement.md

---

### Task 0: 建立离线基线并锁定修改边界

**Files:**

- Test: tests/test_product_gallery.py
- No source changes

- [x] **Step 1: 记录当前工作区状态**

Run:

~~~powershell
git -C D:\DataAnt status --short --branch
~~~

Expected: 命令成功；允许看到任务开始前已经存在的未跟踪项，但不要清理、移动或暂存它们。后续只暂存 app/product_gallery.py、tests/test_product_gallery.py 和本计划文档。

- [x] **Step 2: 运行 gallery 基线测试**

Run:

~~~powershell
Set-Location -LiteralPath 'D:\DataAnt'
& '.\.venv\Scripts\python.exe' -m pytest tests/test_product_gallery.py -q
~~~

Expected:

~~~text
3 passed
~~~

该命令只使用 ProductRecord.success_fixture，不访问真实网站。

- [x] **Step 3: 确认本轮不需要 live run**

不执行 collect-products，也不打开目标站点。设计稿中的两条 PARTIAL 产物只作为后续人工验收的已有离线输入；如果工作区没有该产物，使用测试临时目录验证交互，不伪造或下载运行时文件。

---

### Task 1: 先写质量摘要、缺失字段和交互契约的失败测试

**Files:**

- Modify: tests/test_product_gallery.py:1-49

- [x] **Step 1: 扩展测试导入并添加确定性混合快照 fixture**

将测试导入调整为：

~~~python
from dataclasses import replace

from app.product_gallery import render_gallery
from app.product_models import (
    ProductCollection,
    ProductListing,
    ProductRecord,
    ProductStatus,
)
~~~

在现有 gallery() helper 后加入以下完整 fixture。两个 PARTIAL 记录只缺 category；description、primary_image_url 和 brand 被填充，避免测试同时产生其他缺失字段：

~~~python
def quality_gallery() -> str:
    partial_a = replace(
        ProductRecord.success_fixture(
            "2",
            status=ProductStatus.PARTIAL,
            error_message="missing optional fields: category",
        ),
        category="",
        description="Partial product A",
        primary_image_url="https://web-scraping.dev/assets/products/2.webp",
        brand="Brand A",
    )
    partial_b = replace(
        ProductRecord.success_fixture(
            "3",
            status=ProductStatus.PARTIAL,
            error_message="missing optional fields: category",
        ),
        category="   ",
        description="Partial product B",
        primary_image_url="https://web-scraping.dev/assets/products/3.webp",
        brand="Brand B",
    )
    failed = ProductRecord.failure(
        ProductListing(
            "4",
            "https://web-scraping.dev/product/4",
            "",
        ),
        ProductStatus.PAGE_CHANGED,
        "Missing required detail fields: name",
    )
    collection = ProductCollection.from_records(
        [
            ProductRecord.success_fixture("1"),
            partial_a,
            partial_b,
            failed,
        ],
        generated_at="2026-07-16T20:00:00+08:00",
        blocked=False,
    )
    return render_gallery(collection)
~~~

- [x] **Step 2: 添加首次绘制质量摘要测试**

加入：

~~~python
def test_gallery_renders_quality_summary_and_missing_field_aggregation() -> None:
    page = quality_gallery()

    assert 'id="summary-quality"' in page
    assert 'id="summary-completeness">1 / 4<' in page
    assert 'id="summary-missing-fields">Missing category: 2<' in page
    assert 'id="summary-context">Showing 4 of 4 records<' in page
~~~

这要求 Python 渲染层从同一 ProductCollection 计算 1/4 完整度和 category 缺失计数，而不是在测试中拼接第二份 summary 数据。

- [x] **Step 3: 添加 PARTIAL、未分类和证据侧栏契约测试**

加入：

~~~python
def test_gallery_exposes_partial_reason_and_uncategorized_contract() -> None:
    page = quality_gallery()

    for fragment in (
        "function missingFieldsFor(product)",
        "function categoryValue(product)",
        "function categoryLabel(product)",
        "var UNCATEGORIZED_VALUE = \"__UNCATEGORIZED__\";",
        "Uncategorized",
        "Missing fields",
        "Original reason",
        "Data quality",
        "aria-live=\"polite\"",
        "aria-label=\"Status: ",
        ".product-card:focus-visible",
    ):
        assert fragment in page
    assert "missing optional fields: category" in page
~~~

该测试同时约束：未分类只作为前端筛选 sentinel；原始 error_message 仍然嵌在离线快照中；证据侧栏必须有数据质量小节。

- [x] **Step 4: 添加时间、筛选后统计和离线依赖测试**

加入：

~~~python
def test_gallery_formats_timestamps_without_character_breaking() -> None:
    page = quality_gallery()

    assert (
        'id="summary-generated">2026-07-16 20:00:00 (+08:00)<'
        in page
    )
    assert "function formatTimestamp(value)" in page
    assert "word-break: normal" in page
    assert "overflow-wrap: normal" in page


def test_gallery_recomputes_summary_for_visible_snapshot() -> None:
    page = quality_gallery()

    assert "function summarizeQuality(items)" in page
    assert "renderSummary(filtered);" in page
    assert "Showing \" + current.total + \" of \" + products.length" in page
    assert "categoryValue(product) !== state.category" in page
    assert "formatTimestamp(product.collected_at)" in page
~~~

将现有自包含测试的禁止依赖断言扩展为：

~~~python
def test_gallery_embeds_data_without_external_script_or_font_dependencies() -> None:
    page = gallery()

    for forbidden in (
        "<script src=",
        "@import url(",
        "@font-face",
        "fetch(",
        "XMLHttpRequest",
        "WebSocket",
    ):
        assert forbidden not in page
    assert '"product_id": "1"' in page
~~~

- [x] **Step 5: 运行新增测试确认它们先失败**

Run:

~~~powershell
Set-Location -LiteralPath 'D:\DataAnt'
& '.\.venv\Scripts\python.exe' -m pytest tests/test_product_gallery.py -q
~~~

Expected: 原有 3 项仍通过；新增断言因 summary-quality、质量 helper、Uncategorized sentinel、时间格式和 JS 函数尚未存在而失败。记录失败内容，不修改模型或 JSON 文件来绕过失败。

---

### Task 2: 实现 Python 首次绘制的质量摘要和时间格式化

**Files:**

- Modify: app/product_gallery.py:1-46, 49-342, 672-689

- [x] **Step 1: 增加质量字段配置和空值判定**

在 app/product_gallery.py 的 imports 中加入 datetime，并把 product_models 导入扩展为 ProductCollection、ProductRecord、ProductStatus：

~~~python
from datetime import datetime
from typing import Final

from app.product_json import product_payload
from app.product_models import ProductCollection, ProductRecord, ProductStatus
~~~

在 _format_money() 前加入以下完整 helper。QUALITY_FIELDS 的顺序同时决定顶部缺失字段摘要的稳定顺序：

~~~python
_QUALITY_FIELDS: Final[tuple[tuple[str, str], ...]] = (
    ("category", "category"),
    ("description", "description"),
    ("primary_image_url", "image"),
    ("brand", "brand"),
)


def _is_blank(value: object) -> bool:
    return value is None or not str(value).strip()


def _missing_quality_fields(record: ProductRecord) -> tuple[str, ...]:
    if record.status is not ProductStatus.PARTIAL:
        return ()
    return tuple(
        label
        for field_name, label in _QUALITY_FIELDS
        if _is_blank(getattr(record, field_name))
    )


def _quality_detail(records: tuple[ProductRecord, ...]) -> str:
    counts = {label: 0 for _, label in _QUALITY_FIELDS}
    for record in records:
        for label in _missing_quality_fields(record):
            counts[label] += 1

    parts = [
        f"Missing {label}: {counts[label]}"
        for _, label in _QUALITY_FIELDS
        if counts[label]
    ]
    return " · ".join(parts) if parts else "Fields complete"


def _format_timestamp(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return "—"
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text

    formatted = parsed.strftime("%Y-%m-%d %H:%M:%S")
    compact_offset = parsed.strftime("%z")
    if not compact_offset:
        return formatted
    offset = compact_offset[:3] + ":" + compact_offset[3:]
    return f"{formatted} ({offset})"
~~~

- [x] **Step 2: 为摘要卡增加首次绘制的确定性节点**

在 _TEMPLATE 的 summary-grid 中保留现有 Total、Success、Partial、Failed、Generated 卡片，并在 Generated 后加入：

~~~html
<div class="summary-card" data-tone="quality" id="summary-quality">
    <span class="label">Data quality</span>
    <span class="value" id="summary-completeness">__QUALITY_COMPLETE__ / __QUALITY_TOTAL__</span>
    <span class="detail" id="summary-missing-fields">__QUALITY_MISSING__</span>
</div>
~~~

在 summary-grid 结束后、layout 开始前加入：

~~~html
<p class="summary-context" id="summary-context">
    Showing __TOTAL__ of __TOTAL__ records
</p>
~~~

修改 Generated 卡片的值节点，给它增加 timestamp class，保持现有 id：

~~~html
<span class="value timestamp" id="summary-generated">__GENERATED__</span>
~~~

这些节点先让不执行 JavaScript 的静态 HTML 也具有可读的首屏信息；页面初始化后由 JS 根据筛选结果更新。

- [x] **Step 3: 在 render_gallery() 中注入质量占位值和格式化时间**

将现有 render_gallery() 函数替换为：

~~~python
def render_gallery(collection: ProductCollection) -> str:
    embedded = (
        json.dumps(product_payload(collection), ensure_ascii=False)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )
    summary = collection.summary
    quality_missing = _quality_detail(collection.records)
    generated_label = _format_timestamp(collection.generated_at)
    return (
        _TEMPLATE
        .replace("__EMBEDDED_DATA__", embedded)
        .replace("__TOTAL__", str(summary.total))
        .replace("__SUCCESS__", str(summary.success))
        .replace("__PARTIAL__", str(summary.partial))
        .replace("__FAILED__", str(summary.failed))
        .replace("__QUALITY_COMPLETE__", str(summary.success))
        .replace("__QUALITY_TOTAL__", str(summary.total))
        .replace("__QUALITY_MISSING__", html.escape(quality_missing))
        .replace("__GENERATED__", html.escape(generated_label))
    )
~~~

不要把 quality_missing 写入 product_payload；它是从同一个 collection.records 派生的首屏展示值，products.json 仍保持 schema_version 1 和原有字段。

- [x] **Step 4: 运行 Python 首屏测试**

Run:

~~~powershell
Set-Location -LiteralPath 'D:\DataAnt'
& '.\.venv\Scripts\python.exe' -m pytest tests/test_product_gallery.py -k "quality_summary or timestamps" -q
~~~

Expected: 质量摘要和时间格式测试通过；涉及 JavaScript sentinel、筛选统计和证据侧栏的测试仍可能失败，说明下一任务仍有明确的红灯目标。

---

### Task 3: 实现内嵌快照派生的未分类筛选和动态质量统计

**Files:**

- Modify: app/product_gallery.py:_TEMPLATE JavaScript block around escapeHtml(), applyFilters(), renderSummary(), init()

- [x] **Step 1: 在 JavaScript 中定义唯一的 UI sentinel 和质量字段映射**

在 formatMoney() 后加入：

~~~javascript
var UNCATEGORIZED_VALUE = "__UNCATEGORIZED__";
var QUALITY_FIELDS = [
    { key: "category", label: "category" },
    { key: "description", label: "description" },
    { key: "primary_image_url", label: "image" },
    { key: "brand", label: "brand" }
];

function isBlank(value) {
    return value === null || value === undefined || String(value).trim() === "";
}

function categoryValue(product) {
    var value = product ? product.category : "";
    return isBlank(value) ? UNCATEGORIZED_VALUE : String(value);
}

function categoryLabel(product) {
    var value = categoryValue(product);
    return value === UNCATEGORIZED_VALUE ? "Uncategorized" : value;
}

function missingFieldsFor(product) {
    if (!product || product.status !== "PARTIAL") return [];
    var missing = [];
    for (var i = 0; i < QUALITY_FIELDS.length; i++) {
        var field = QUALITY_FIELDS[i];
        if (isBlank(product[field.key])) missing.push(field.label);
    }
    return missing;
}

function statusLabel(product) {
    if (!product || product.status === "SUCCESS") return "Complete";
    if (product.status === "PARTIAL") return "Partial";
    return "Failed";
}

function shortError(value) {
    var text = String(value || "").trim();
    if (text.length <= 120) return text;
    return text.slice(0, 117) + "…";
}

function reasonText(product) {
    if (!product || product.status === "SUCCESS") return "";
    var missing = missingFieldsFor(product);
    if (product.status === "PARTIAL" && missing.length) {
        return "Missing " + missing.join(", ");
    }
    return shortError(product.error_message);
}

function summarizeQuality(items) {
    var result = {
        total: items.length,
        success: 0,
        partial: 0,
        failed: 0,
        missing: {}
    };
    for (var i = 0; i < items.length; i++) {
        var product = items[i];
        if (product.status === "SUCCESS") {
            result.success += 1;
        } else if (product.status === "PARTIAL") {
            result.partial += 1;
            var missing = missingFieldsFor(product);
            for (var j = 0; j < missing.length; j++) {
                var label = missing[j];
                result.missing[label] = (result.missing[label] || 0) + 1;
            }
        } else {
            result.failed += 1;
        }
    }
    return result;
}

function formatMissingSummary(summary) {
    var parts = [];
    for (var i = 0; i < QUALITY_FIELDS.length; i++) {
        var label = QUALITY_FIELDS[i].label;
        if (summary.missing[label]) {
            parts.push("Missing " + label + ": " + summary.missing[label]);
        }
    }
    return parts.length ? parts.join(" · ") : "Fields complete";
}

function formatTimestamp(value) {
    if (isBlank(value)) return "—";
    var text = String(value).trim();
    var match = text.match(/^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})(?:\.\d+)?(Z|[+-]\d{2}:\d{2})?$/);
    if (!match) return text;
    var offset = match[3] ? (match[3] === "Z" ? "+00:00" : match[3]) : "";
    return match[1] + " " + match[2] + (offset ? " (" + offset + ")" : "");
}
~~~

The sentinel must exist only in state.category and option.value; never mutate product.category or the embedded JSON.

- [x] **Step 2: 替换分类选项生成逻辑**

将 uniqueValues() 保留给 status 使用，并在其后加入：

~~~javascript
function uniqueCategoryValues(items) {
    var seen = Object.create(null);
    var categories = [];
    seen[UNCATEGORIZED_VALUE] = true;
    categories.push(UNCATEGORIZED_VALUE);

    for (var i = 0; i < items.length; i++) {
        var value = categoryValue(items[i]);
        if (!seen[value]) {
            seen[value] = true;
            if (value !== UNCATEGORIZED_VALUE) categories.push(value);
        }
    }
    var named = categories.slice(1);
    named.sort();
    return [UNCATEGORIZED_VALUE].concat(named);
}
~~~

将 populateSelect() 替换为支持显示值格式化的完整实现：

~~~javascript
function populateSelect(selectId, values, allLabel, labelForValue) {
    var select = document.getElementById(selectId);
    if (!select) return;
    select.innerHTML = "";
    var defaultOpt = document.createElement("option");
    defaultOpt.value = "";
    defaultOpt.textContent = allLabel;
    select.appendChild(defaultOpt);
    for (var i = 0; i < values.length; i++) {
        var opt = document.createElement("option");
        opt.value = values[i];
        opt.textContent = labelForValue ? labelForValue(values[i]) : values[i];
        select.appendChild(opt);
    }
}
~~~

- [x] **Step 3: 让筛选逻辑统一使用 categoryValue()**

在 applyFilters() 的 category 判断中，将：

~~~javascript
if (state.category && (product.category || "") !== state.category) return false;
~~~

替换为：

~~~javascript
if (state.category && categoryValue(product) !== state.category) return false;
~~~

这样空字符串、空白字符串和缺失 category 都由同一个 sentinel 命中“Uncategorized”。

- [x] **Step 4: 让 renderSummary() 从当前可见数组重新计算**

将现有 renderSummary() 替换为：

~~~javascript
function renderSummary(items) {
    var current = summarizeQuality(items);
    var total = document.getElementById("summary-total");
    var success = document.getElementById("summary-success");
    var partial = document.getElementById("summary-partial");
    var failed = document.getElementById("summary-failed");
    var generated = document.getElementById("summary-generated");
    var completeness = document.getElementById("summary-completeness");
    var missingFields = document.getElementById("summary-missing-fields");
    var context = document.getElementById("summary-context");

    if (total) total.textContent = current.total;
    if (success) success.textContent = current.success;
    if (partial) partial.textContent = current.partial;
    if (failed) failed.textContent = current.failed;
    if (generated) generated.textContent = formatTimestamp(generatedAt);
    if (completeness) {
        completeness.textContent = current.success + " / " + current.total;
    }
    if (missingFields) {
        missingFields.textContent = formatMissingSummary(current);
    }
    if (context) {
        context.textContent =
            "Showing " + current.total + " of " + products.length + " records";
    }
}
~~~

在 renderProducts() 中，取得 filtered 后立即调用 renderSummary(filtered)，然后再处理 empty-state 或卡片渲染：

~~~javascript
function renderProducts() {
    var grid = document.getElementById("product-grid");
    if (!grid) return;
    var filtered = applyFilters();
    renderSummary(filtered);
    if (filtered.length === 0) {
        grid.innerHTML = '<div class="empty-state">No products match the current filters.</div>';
        return;
    }
    var html = "";
    for (var i = 0; i < filtered.length; i++) {
        html += cardMarkup(filtered[i]);
    }
    grid.innerHTML = html;
    var cards = grid.querySelectorAll(".product-card");
    for (var j = 0; j < cards.length; j++) {
        (function (card) {
            var id = card.getAttribute("data-id");
            card.addEventListener("click", function () { selectProduct(id); });
            card.addEventListener("keydown", function (event) {
                if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    selectProduct(id);
                }
            });
        })(cards[j]);
    }
}
~~~

- [x] **Step 5: 更新 init() 并删除第二份 summary 依赖**

保留 payload.products 作为唯一运行时数据数组，删除不再使用的 payload.summary 局部变量。将 init() 替换为：

~~~javascript
function init() {
    populateSelect(
        "category-filter",
        uniqueCategoryValues(products),
        "All categories",
        function (value) {
            return value === UNCATEGORIZED_VALUE ? "Uncategorized" : value;
        }
    );
    populateSelect(
        "status-filter",
        uniqueValues(products, "status"),
        "All statuses"
    );
    renderProducts();
    attachControls();
    if (products.length > 0) {
        selectProduct(products[0].product_id);
    }
}
~~~

- [x] **Step 6: 运行动态契约测试并提交可工作的筛选实现**

Run:

~~~powershell
Set-Location -LiteralPath 'D:\DataAnt'
& '.\.venv\Scripts\python.exe' -m pytest tests/test_product_gallery.py -q
~~~

Expected: gallery test file 全部通过；HTML 仍没有外部 script、font、fetch、XHR 或 WebSocket 依赖。

Commit:

~~~powershell
git -C D:\DataAnt add app/product_gallery.py tests/test_product_gallery.py
git -C D:\DataAnt commit -m "feat: add gallery quality filtering and summaries"
~~~

Expected: commit 成功；暂存区只包含两个 gallery 源码/测试文件，不包含 outputs、artifacts、browser-profile 或无关未跟踪项。

---

### Task 4: 增强卡片原因、证据侧栏、时间显示、布局和可访问性

**Files:**

- Modify: app/product_gallery.py:_TEMPLATE CSS block and cardMarkup(), fieldRow(), renderEvidence()

- [x] **Step 1: 增加可见状态原因和键盘焦点 CSS**

在现有 CSS 中加入或替换为以下规则：

~~~css
.summary-card[data-tone="quality"] .value { color: var(--accent); }
.summary-card .detail {
    color: var(--muted);
    font-size: 12px;
    line-height: 1.35;
}
.summary-context {
    margin: -12px 0 24px;
    color: var(--muted);
    font-size: 13px;
}
.timestamp {
    font-family: ui-monospace, SFMono-Regular, "SF Mono", Consolas,
        "Liberation Mono", Menlo, monospace;
    color: var(--text);
    white-space: normal;
    word-break: normal;
    overflow-wrap: normal;
}
.status-line {
    display: flex;
    align-items: baseline;
    flex-wrap: wrap;
    gap: 8px;
}
.quality-note {
    color: var(--muted);
    font-size: 12px;
}
.quality-note[data-status="PARTIAL"] { color: var(--partial); }
.quality-note[data-status="PAGE_CHANGED"],
.quality-note[data-status="NETWORK_ERROR"],
.quality-note[data-status="BLOCKED"],
.quality-note[data-status="UNEXPECTED_ERROR"] { color: var(--failed); }
.product-card:focus-visible,
.toolbar input:focus-visible,
.toolbar select:focus-visible,
.evidence-panel a:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 2px;
}
.evidence-section {
    border-top: 1px solid var(--line);
    padding-top: 12px;
}
.evidence-section h3 {
    margin: 0 0 8px;
    font-size: 13px;
    color: var(--text);
}
~~~

保留现有颜色和深色背景；质量提示使用琥珀色，只有真实失败状态继续使用失败红色。

- [x] **Step 2: 调整摘要、卡片网格和窄屏侧栏**

将 summary-grid 和 product-grid 的列规则调整为：

~~~css
.summary-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: var(--gap);
    margin-bottom: 24px;
}
.product-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(min(100%, 260px), 1fr));
    gap: var(--gap);
}
~~~

在现有 max-width: 960px media query 中补充：

~~~css
@media (max-width: 960px) {
    .layout { grid-template-columns: 1fr; }
    .evidence-panel {
        position: static;
        max-height: none;
    }
}
~~~

保留 max-width: 720px 的 toolbar 两列折叠。卡片至少保持 260px 的可读宽度；窄屏使用 100% 退化为单列；证据侧栏在宽屏仍为固定 340px，在窄屏自然出现在商品列表下方。

- [x] **Step 3: 更新摘要 HTML 的 live region 和时间 class**

将 summary-grid 起始标签替换为：

~~~html
<section class="summary-grid" id="summary-grid" aria-live="polite" aria-atomic="true">
~~~

保留搜索框、分类 select、状态 select 的现有 aria-label，并保持 product-card 的 tabindex="0"、role="button" 以及 Enter/Space 键盘事件。

- [x] **Step 4: 替换 cardMarkup()，让状态不依赖颜色**

将 cardMarkup() 替换为以下实现。status 保留原始枚举用于 data-status 和 aria-label；可读 badge 文本和质量原因同时呈现：

~~~javascript
function cardMarkup(product) {
    var visual = visualFor(product);
    var currentPrice = formatMoney(product.current_price, product.currency);
    var originalPrice =
        product.original_price !== null && product.original_price !== undefined
            ? formatMoney(product.original_price, product.currency)
            : "";
    var selected = product.product_id === state.selectedId ? " selected" : "";
    var gradient =
        "linear-gradient(135deg, " + visual.palette.start + " 0%, " +
        visual.palette.end + " 100%)";
    var categoryLine =
        '<div class="category">' + escapeHtml(categoryLabel(product)) + "</div>";
    var originalLine = originalPrice
        ? '<span class="price-original">' + escapeHtml(originalPrice) + "</span>"
        : "";
    var rawStatus = product.status || "UNEXPECTED_ERROR";
    var note = reasonText(product);
    var noteLine = note
        ? '<span class="quality-note" data-status="' +
          escapeHtml(rawStatus) + '">' + escapeHtml(note) + "</span>"
        : "";

    return "" +
        '<article class="product-card' + selected +
        '" data-id="' + escapeHtml(product.product_id) +
        '" tabindex="0" role="button" aria-label="Select ' +
        escapeHtml(product.name || product.product_id) + '">' +
        '<div class="visual" style="background:' + gradient +
        "; color:" + visual.palette.ink + ';">' +
        escapeHtml(visual.letter) +
        iconMarkup(product.category) +
        "</div>" +
        '<div class="body">' +
        '<div class="name">' + escapeHtml(product.name || product.product_id) + "</div>" +
        '<div class="price-row">' +
        '<span class="price-current">' + escapeHtml(currentPrice) + "</span>" +
        originalLine +
        "</div>" +
        categoryLine +
        '<div class="status-line">' +
        '<span class="badge" data-status="' + escapeHtml(rawStatus) +
        '" aria-label="Status: ' + escapeHtml(statusLabel(product)) + '">' +
        escapeHtml(statusLabel(product)) + "</span>" +
        noteLine +
        "</div>" +
        "</div>" +
        "</article>";
}
~~~

- [x] **Step 5: 让 fieldRow() 支持 timestamp class 并增强 renderEvidence()**

将 fieldRow() 替换为：

~~~javascript
function fieldRow(label, value, options) {
    options = options || {};
    var content;
    var valueClass = options.className ? " " + options.className : "";
    if (value === null || value === undefined || value === "") {
        content = '<span class="val muted">—</span>';
    } else if (options.mono) {
        content = "<pre>" + escapeHtml(value) + "</pre>";
    } else if (options.link) {
        content =
            '<a class="val' + valueClass + '" href="' + escapeHtml(value) +
            '" target="_blank" rel="noopener noreferrer">' +
            escapeHtml(value) + "</a>";
    } else {
        content =
            '<span class="val' + valueClass + '">' +
            escapeHtml(value) + "</span>";
    }
    return '<div class="row"><span class="key">' +
        escapeHtml(label) + "</span>" + content + "</div>";
}
~~~

将 renderEvidence() 替换为：

~~~javascript
function renderEvidence(product) {
    var panel = document.getElementById("evidence-panel");
    if (!panel) return;
    var empty = document.getElementById("evidence-empty");
    if (!product) {
        if (empty) empty.style.display = "";
        var extra = panel.querySelectorAll(":scope > *:not(h2):not(.empty)");
        for (var i = 0; i < extra.length; i++) extra[i].remove();
        return;
    }

    if (empty) empty.style.display = "none";
    var extraRows = panel.querySelectorAll(":scope > *:not(h2):not(.empty)");
    for (var k = 0; k < extraRows.length; k++) extraRows[k].remove();

    var missing = missingFieldsFor(product);
    var qualitySection = document.createElement("section");
    qualitySection.className = "evidence-section";
    qualitySection.setAttribute("aria-labelledby", "evidence-quality-heading");
    qualitySection.innerHTML =
        '<h3 id="evidence-quality-heading">Data quality</h3>' +
        fieldRow(
            "Missing fields",
            missing.length ? missing.join(", ") : "Fields complete"
        ) +
        fieldRow("Original reason", product.error_message, { mono: true });
    panel.appendChild(qualitySection);

    var rows = [
        fieldRow("Name", product.name),
        fieldRow("Description", product.description),
        fieldRow("Category", categoryLabel(product)),
        fieldRow("Brand", product.brand),
        fieldRow("Current price", formatMoney(product.current_price, product.currency)),
        fieldRow(
            "Original price",
            product.original_price !== null && product.original_price !== undefined
                ? formatMoney(product.original_price, product.currency)
                : null
        ),
        fieldRow("Currency", product.currency),
        fieldRow(
            "Variants",
            product.variant_count !== undefined && product.variant_count !== null
                ? product.variant_count
                : 0
        ),
        fieldRow("Status", product.status),
        fieldRow(
            "Collected at",
            formatTimestamp(product.collected_at),
            { className: "timestamp" }
        ),
        fieldRow("Product ID", product.product_id, { mono: true }),
        fieldRow("Primary image URL", product.primary_image_url, { mono: true }),
        fieldRow("Source URL", product.product_url, { link: true })
    ];

    for (var r = 0; r < rows.length; r++) {
        var div = document.createElement("div");
        div.innerHTML = rows[r];
        panel.appendChild(div.firstChild);
    }
}
~~~

Data quality 小节同时显示派生的缺失字段和原始 error_message；完整记录显示 Fields complete，失败记录显示原始错误文本但不伪装成 PARTIAL。

- [x] **Step 6: 运行 gallery 测试确认视觉层改动不破坏行为**

Run:

~~~powershell
Set-Location -LiteralPath 'D:\DataAnt'
& '.\.venv\Scripts\python.exe' -m pytest tests/test_product_gallery.py -q
~~~

Expected: 全部 gallery 测试通过。尤其确认 </script> escaping 断言仍通过，不能为了插入质量数据而直接把未经转义的 product 字段拼入 HTML。

Commit:

~~~powershell
git -C D:\DataAnt add app/product_gallery.py tests/test_product_gallery.py
git -C D:\DataAnt commit -m "feat: clarify product quality in gallery cards"
~~~

---

### Task 5: 执行全量离线验证和当前产物人工验收

**Files:**

- Verify: app/product_gallery.py
- Verify: tests/test_product_gallery.py
- Verify: scripts/verify_products.py
- Verify: tests/test_project_config.py
- Runtime output: none committed

- [x] **Step 1: 运行 gallery、bundle 和项目配置测试**

Run:

~~~powershell
Set-Location -LiteralPath 'D:\DataAnt'
& '.\.venv\Scripts\python.exe' -m pytest tests/test_product_gallery.py tests/test_product_output_bundle.py tests/test_verify_products.py tests/test_project_config.py -q
~~~

Expected: 全部通过；bundle verifier 的外部依赖规则仍然禁止 script src、外部字体、fetch、XHR 和 WebSocket。本轮不修改 verifier，因为现有 verifier 已覆盖这些静态契约。

- [x] **Step 2: 运行全量离线测试和依赖检查**

Run:

~~~powershell
Set-Location -LiteralPath 'D:\DataAnt'
& '.\.venv\Scripts\python.exe' -m pytest -q
& '.\.venv\Scripts\python.exe' -m pip check
git -C D:\DataAnt diff --check
~~~

Expected：

- pytest 退出码 0；
- pip check 输出 No broken requirements found；
- git diff --check 退出码 0 且无输出；
- 全程不启动浏览器、不访问 movie.douban.com、不访问 web-scraping.dev。

- [x] **Step 3: 对已有 bundle 执行离线 verifier**

如果已有真实验收目录 D:\DataAnt\outputs\web-scraping-dev-demo 存在，只对它运行：

~~~powershell
Set-Location -LiteralPath 'D:\DataAnt'
$bundle = 'D:\DataAnt\outputs\web-scraping-dev-demo'
if (Test-Path -LiteralPath $bundle) {
    & '.\.venv\Scripts\python.exe' -m scripts.verify_products --output-dir $bundle
}
~~~

Expected：若目录存在，输出 products、unique_ids、success、partial、failed 五项计数并退出码 0；若目录不存在，不启动 live run，bundle 一致性已由测试临时目录覆盖。不要把该目录中的 gallery.html、products.json、products.xlsx 复制到 Git 跟踪路径。

- [x] **Step 4: 使用已有真实 PARTIAL 画廊做人工验收**

只在已有本地产物存在时打开：

~~~powershell
$gallery = 'D:\DataAnt\outputs\web-scraping-dev-demo\gallery.html'
if (Test-Path -LiteralPath $gallery) {
    Start-Process -FilePath $gallery
}
~~~

在断网或 DevTools Network 面板中确认：

- 顶部可一眼读出 Total 2、Partial 2、Failed 0；Data quality 显示 0 / 2 和 Missing category: 2。
- 两张 PARTIAL 卡片同时显示 Partial 和 Missing category，不靠颜色单独传达状态；失败卡片显示 error_message 摘要；完整卡片不显示质量警告。
- 分类筛选出现固定 Uncategorized 选项；选择后只保留两条空 category 商品，顶部统计同步为当前可见数，同时 summary-context 保留原始总数。
- 点击任意卡片后，证据侧栏显示 Data quality、Missing fields、Original reason、Category: Uncategorized、来源 URL、Product ID 和完整 Collected at。
- 生成时间和采集时间显示为类似 2026-07-17 12:42:44 (+08:00) 的文本；窄屏只能在空格等自然断点换行，不按字符拆分。
- Tab 可以聚焦筛选控件和卡片，Enter/Space 可以选择卡片；焦点轮廓清晰。
- 页面加载后 Network 面板没有自动请求；断网或直接双击 HTML 时搜索、筛选、排序和侧栏更新仍可用。

如果真实 bundle 不存在，使用 tests/test_product_output_bundle.py 生成的临时 gallery.html 做同一套交互检查，不为人工验收临时创建 outputs/ 中的提交文件。

- [x] **Step 5: 扫描最终变更并完成交付提交**

Run:

~~~powershell
git -C D:\DataAnt status --short
git -C D:\DataAnt diff -- app/product_gallery.py tests/test_product_gallery.py
~~~

Expected：差异只涉及画廊渲染、样式、内嵌 JavaScript、gallery 测试和本计划文档；不存在 model、json、采集器、live 门禁或运行时产物变更。确认后提交本轮实现：

~~~powershell
git -C D:\DataAnt add app/product_gallery.py tests/test_product_gallery.py docs/superpowers/plans/2026-07-17-product-gallery-quality-visual-enhancement.md
git -C D:\DataAnt commit -m "feat: enhance product gallery data quality visuals"
~~~

不要使用 git add -A；不要暂存 outputs/、artifacts/、browser-profile/ 或任务开始前已有的无关未跟踪文件。

## 收尾审计记录（2026-07-17）

- 已检查既有实现提交：`e91bfbc`、`22b9441`、`0b1a2a5`；本次复核范围以 `e7ba058..0b1a2a5` 为基线，避免把更早的采集器和输出包提交误判为本轮改动。
- 已补齐并验证 5 项渲染层收尾修复：嵌入 JSON 最后替换占位符、来源 URL 白名单校验、无失败原因时的兜底文案、失败记录下的质量摘要语义，以及证据侧栏时间戳的不可拆词样式。
- 离线验证通过：`.venv` 全量 `243 passed`；gallery 目标测试 `12 passed`；`.venv` `pip check` 输出 `No broken requirements found`；bundle verifier 输出 `products: 2`、`unique_ids: 2`、`success: 0`、`partial: 2`、`failed: 0`。
- 已使用现有 PARTIAL bundle 做本地人工验收：摘要、`Uncategorized` 筛选、证据侧栏、键盘/焦点和时间格式均可用；仅绑定 `127.0.0.1`，未访问目标站点，页面无外部脚本、字体或网络请求依赖（浏览器仅报告缺失 favicon 的 404）。
- 全量测试和依赖检查均使用仓库 `.venv`；系统 Anaconda 环境的 `DrissionPage` 缺失及 `protobuf` 冲突不作为项目失败依据。
- Task 5 Step 5 已完成本地提交；当前未推送远端，也未处理既有未跟踪目录和运行产物。

## 规范覆盖检查

- 顶部总数、成功、部分、失败和生成时间：Task 2、Task 3。
- 完整度 success / total 与按字段聚合的缺失摘要：Task 1、Task 2、Task 3。
- PARTIAL 缺失字段、卡片短原因、证据侧栏原始原因：Task 1、Task 4。
- 空字符串、空白字符串和缺失 category 的 Uncategorized 选项与筛选：Task 1、Task 3、Task 4。
- 筛选后可见统计和原始总数上下文：Task 3。
- 生成/采集时间格式、卡片密度、宽屏固定侧栏、窄屏下移：Task 4。
- 深色主题、高对比状态色、可读文本、aria-label、键盘焦点：Task 4。
- 同一份内嵌 JSON、无 schema 变化、无外部脚本/字体/fetch/XHR/WebSocket：Task 1、Task 3、Task 5。
- 不访问目标站、不修改采集器和 live 规则、不提交运行时文件：所有 Task 的不变量与 Task 5。
- 现有测试、bundle verifier、CI 静态约束：Task 5。

## 回滚边界

如果视觉改动导致 gallery 静态契约失败，只回滚 app/product_gallery.py 和对应 gallery 测试的展示层提交，保留已验证的 app/product_models.py、app/product_json.py、采集器、输出包和 live 门禁改动。不要用回滚展示层的方式恢复或修改任何真实采集结果，也不要删除 outputs/、artifacts/ 或 browser-profile/ 中的用户运行时文件。
