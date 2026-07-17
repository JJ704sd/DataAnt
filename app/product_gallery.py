from __future__ import annotations

import html
import json
from typing import Final

from app.product_json import product_payload
from app.product_models import ProductCollection


_CATEGORY_PALETTES: Final[tuple[tuple[str, str, str], ...]] = (
    ("#0f766e", "#0ea5e9", "#0f172a"),  # teal -> sky
    ("#7c3aed", "#ec4899", "#1e1b4b"),  # violet -> pink
    ("#ea580c", "#facc15", "#3f1d0f"),  # orange -> amber
    ("#16a34a", "#22d3ee", "#022c22"),  # green -> cyan
    ("#db2777", "#a855f7", "#3b0764"),  # pink -> fuchsia
    ("#2563eb", "#22c55e", "#0b1a2b"),  # blue -> green
    ("#9333ea", "#f97316", "#2a1140"),  # purple -> orange
    ("#0891b2", "#84cc16", "#042f2e"),  # cyan -> lime
)


def _hash_to_palette(seed: str) -> tuple[str, str, str]:
    digest = 0
    for index, char in enumerate(seed.encode("utf-8")):
        digest = (digest * 131 + char + index) & 0xFFFFFFFF
    return _CATEGORY_PALETTES[digest % len(_CATEGORY_PALETTES)]


def _initial_letter(name: str) -> str:
    cleaned = name.strip()
    if not cleaned:
        return "?"
    for char in cleaned:
        if char.isalpha():
            return char.upper()
    return "?"


def _format_money(amount: float | None, currency: str) -> str:
    if amount is None:
        return "—"
    label = currency or ""
    if label:
        return f"{label} {amount:.2f}"
    return f"{amount:.2f}"


_TEMPLATE: Final[str] = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>web-scraping.dev Product Gallery</title>
<style>
:root {
    --bg: #0f172a;
    --panel: #1e293b;
    --panel-2: #111827;
    --line: #334155;
    --text: #e2e8f0;
    --muted: #94a3b8;
    --accent: #38bdf8;
    --success: #22c55e;
    --partial: #f59e0b;
    --failed: #ef4444;
    --blocked: #a855f7;
    --radius: 14px;
    --gap: 16px;
    --font: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue",
            Arial, "Noto Sans", "PingFang SC", "Hiragino Sans GB",
            "Microsoft YaHei", sans-serif;
}
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; background: var(--bg); color: var(--text); }
body {
    font-family: var(--font);
    font-size: 15px;
    line-height: 1.5;
    min-height: 100vh;
    padding: 24px;
}
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
header.page-header {
    display: flex;
    flex-direction: column;
    gap: 6px;
    margin-bottom: 24px;
}
header.page-header h1 {
    margin: 0;
    font-size: 26px;
    font-weight: 700;
    letter-spacing: -0.01em;
}
header.page-header .source {
    color: var(--muted);
    font-size: 13px;
}
.summary-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: var(--gap);
    margin-bottom: 24px;
}
.summary-card {
    background: var(--panel);
    border: 1px solid var(--line);
    border-radius: var(--radius);
    padding: 16px 18px;
    display: flex;
    flex-direction: column;
    gap: 6px;
}
.summary-card .label {
    color: var(--muted);
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
}
.summary-card .value {
    font-size: 24px;
    font-weight: 700;
}
.summary-card[data-tone="success"] .value { color: var(--success); }
.summary-card[data-tone="partial"] .value { color: var(--partial); }
.summary-card[data-tone="failed"] .value { color: var(--failed); }
.summary-card[data-tone="blocked"] .value { color: var(--blocked); }
.layout {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 340px;
    gap: var(--gap);
}
@media (max-width: 960px) {
    .layout { grid-template-columns: 1fr; }
}
.toolbar {
    display: grid;
    grid-template-columns: 2fr 1fr 1fr 1fr;
    gap: var(--gap);
    margin-bottom: var(--gap);
}
@media (max-width: 720px) {
    .toolbar { grid-template-columns: 1fr 1fr; }
}
.toolbar input, .toolbar select {
    background: var(--panel);
    color: var(--text);
    border: 1px solid var(--line);
    border-radius: 10px;
    padding: 9px 12px;
    font: inherit;
}
.toolbar input:focus, .toolbar select:focus {
    outline: 2px solid var(--accent);
    outline-offset: 1px;
}
.product-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
    gap: var(--gap);
}
.product-card {
    background: var(--panel);
    border: 1px solid var(--line);
    border-radius: var(--radius);
    overflow: hidden;
    cursor: pointer;
    display: flex;
    flex-direction: column;
    transition: transform 0.15s ease, border-color 0.15s ease;
}
.product-card:hover { transform: translateY(-2px); border-color: var(--accent); }
.product-card.selected { border-color: var(--accent); box-shadow: 0 0 0 2px rgba(56, 189, 248, 0.25); }
.product-card .visual {
    aspect-ratio: 16 / 9;
    display: flex;
    align-items: center;
    justify-content: center;
    color: rgba(255, 255, 255, 0.94);
    font-size: 48px;
    font-weight: 700;
    letter-spacing: -0.04em;
    position: relative;
}
.product-card .visual svg.icon {
    position: absolute;
    top: 12px;
    right: 12px;
    width: 28px;
    height: 28px;
    opacity: 0.75;
}
.product-card .body {
    padding: 14px 16px 16px;
    display: flex;
    flex-direction: column;
    gap: 8px;
}
.product-card .name {
    font-weight: 600;
    font-size: 15px;
    line-height: 1.35;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
}
.product-card .price-row {
    display: flex;
    align-items: baseline;
    gap: 8px;
}
.product-card .price-current {
    color: var(--accent);
    font-weight: 700;
    font-size: 17px;
}
.product-card .price-original {
    color: var(--muted);
    text-decoration: line-through;
    font-size: 13px;
}
.product-card .category {
    color: var(--muted);
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}
.product-card .badge {
    align-self: flex-start;
    padding: 2px 8px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.04em;
    text-transform: uppercase;
}
.badge[data-status="SUCCESS"] { background: rgba(34, 197, 94, 0.18); color: var(--success); }
.badge[data-status="PARTIAL"] { background: rgba(245, 158, 11, 0.18); color: var(--partial); }
.badge[data-status="PAGE_CHANGED"] { background: rgba(239, 68, 68, 0.18); color: var(--failed); }
.badge[data-status="NETWORK_ERROR"] { background: rgba(239, 68, 68, 0.18); color: var(--failed); }
.badge[data-status="BLOCKED"] { background: rgba(168, 85, 247, 0.18); color: var(--blocked); }
.badge[data-status="UNEXPECTED_ERROR"] { background: rgba(148, 163, 184, 0.18); color: var(--muted); }
.evidence-panel {
    background: var(--panel);
    border: 1px solid var(--line);
    border-radius: var(--radius);
    padding: 20px;
    display: flex;
    flex-direction: column;
    gap: 12px;
    position: sticky;
    top: 24px;
    align-self: start;
    max-height: calc(100vh - 48px);
    overflow-y: auto;
}
.evidence-panel h2 {
    margin: 0;
    font-size: 16px;
    font-weight: 700;
}
.evidence-panel .row {
    display: flex;
    flex-direction: column;
    gap: 2px;
}
.evidence-panel .row .key {
    color: var(--muted);
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
}
.evidence-panel .row .val {
    color: var(--text);
    font-size: 14px;
    word-break: break-word;
}
.evidence-panel .row .val.muted { color: var(--muted); }
.evidence-panel pre {
    background: var(--panel-2);
    border: 1px solid var(--line);
    border-radius: 8px;
    padding: 8px 10px;
    margin: 0;
    font-family: ui-monospace, SFMono-Regular, "SF Mono", Consolas,
        "Liberation Mono", Menlo, monospace;
    font-size: 12px;
    color: var(--muted);
    white-space: pre-wrap;
    word-break: break-all;
}
.evidence-panel .empty {
    color: var(--muted);
    font-size: 13px;
}
.empty-state {
    grid-column: 1 / -1;
    text-align: center;
    padding: 48px 16px;
    color: var(--muted);
}
</style>
</head>
<body>
<header class="page-header">
    <h1>web-scraping.dev Product Gallery</h1>
    <div class="source">Data source: web-scraping.dev — local snapshot, no remote requests on open.</div>
</header>
<section class="summary-grid" id="summary-grid">
    <div class="summary-card" data-tone="total"><span class="label">Total</span><span class="value" id="summary-total">__TOTAL__</span></div>
    <div class="summary-card" data-tone="success"><span class="label">Success</span><span class="value" id="summary-success">__SUCCESS__</span></div>
    <div class="summary-card" data-tone="partial"><span class="label">Partial</span><span class="value" id="summary-partial">__PARTIAL__</span></div>
    <div class="summary-card" data-tone="failed"><span class="label">Failed</span><span class="value" id="summary-failed">__FAILED__</span></div>
    <div class="summary-card" data-tone="meta"><span class="label">Generated</span><span class="value" id="summary-generated">__GENERATED__</span></div>
</section>
<div class="layout">
    <main>
        <div class="toolbar">
            <input id="search" type="search" placeholder="Search by name, brand, description…" aria-label="Search products">
            <select id="category-filter" aria-label="Filter by category">
                <option value="">All categories</option>
            </select>
            <select id="status-filter" aria-label="Filter by status">
                <option value="">All statuses</option>
            </select>
            <select id="price-sort" aria-label="Sort by price">
                <option value="">Default order</option>
                <option value="asc">Price: low to high</option>
                <option value="desc">Price: high to low</option>
            </select>
        </div>
        <section class="product-grid" id="product-grid" aria-live="polite"></section>
    </main>
    <aside class="evidence-panel" id="evidence-panel" aria-label="Collection evidence">
        <h2>Collection Evidence</h2>
        <p class="empty" id="evidence-empty">Select a product to view collection evidence.</p>
    </aside>
</div>
<script id="product-data" type="application/json">__EMBEDDED_DATA__</script>
<script>
(function () {
    var dataNode = document.getElementById("product-data");
    var raw = dataNode ? dataNode.textContent : "null";
    var payload = JSON.parse(raw);
    var products = (payload && payload.products) ? payload.products : [];
    var summary = (payload && payload.summary) ? payload.summary : { total: 0, success: 0, partial: 0, failed: 0 };
    var generatedAt = (payload && payload.generated_at) ? payload.generated_at : "";

    var state = {
        query: "",
        category: "",
        status: "",
        sort: "",
        selectedId: null
    };

    function escapeHtml(value) {
        if (value === null || value === undefined) return "";
        return String(value)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    function formatMoney(amount, currency) {
        if (amount === null || amount === undefined || isNaN(amount)) return "—";
        var label = currency || "";
        var rounded = Number(amount).toFixed(2);
        if (label) return label + " " + rounded;
        return rounded;
    }

    function hashToPalette(seed) {
        var digest = 0;
        for (var i = 0; i < seed.length; i++) {
            digest = ((digest * 131) + seed.charCodeAt(i) + i) & 0xFFFFFFFF;
        }
        var palettes = [
            ["#0f766e", "#0ea5e9", "#0f172a"],
            ["#7c3aed", "#ec4899", "#1e1b4b"],
            ["#ea580c", "#facc15", "#3f1d0f"],
            ["#16a34a", "#22d3ee", "#022c22"],
            ["#db2777", "#a855f7", "#3b0764"],
            ["#2563eb", "#22c55e", "#0b1a2b"],
            ["#9333ea", "#f97316", "#2a1140"],
            ["#0891b2", "#84cc16", "#042f2e"]
        ];
        var palette = palettes[Math.abs(digest) % palettes.length];
        return { start: palette[0], end: palette[1], ink: palette[2] };
    }

    function initialLetter(name) {
        var cleaned = (name || "").trim();
        if (!cleaned) return "?";
        for (var i = 0; i < cleaned.length; i++) {
            var ch = cleaned.charAt(i);
            if (ch && ch.toUpperCase() !== ch.toLowerCase()) return ch.toUpperCase();
        }
        return "?";
    }

    function visualFor(product) {
        var seed = (product && product.category ? product.category : "") + "::" + (product && product.name ? product.name : product && product.product_id ? product.product_id : "");
        var palette = hashToPalette(seed);
        var letter = initialLetter(product && product.name ? product.name : product && product.product_id ? product.product_id : "?");
        return { palette: palette, letter: letter };
    }

    function iconMarkup(category) {
        var key = (category || "").toLowerCase();
        if (key.indexOf("book") !== -1) {
            return '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M4 4h10a4 4 0 0 1 4 4v12H8a4 4 0 0 1-4-4z"/><path d="M4 4v12a4 4 0 0 0 4 4"/></svg>';
        }
        if (key.indexOf("apparel") !== -1 || key.indexOf("clothing") !== -1 || key.indexOf("shirt") !== -1) {
            return '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M4 7l4-3 4 2 4-2 4 3-2 3v9H6v-9z"/></svg>';
        }
        if (key.indexOf("electronic") !== -1 || key.indexOf("gadget") !== -1) {
            return '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><rect x="3" y="6" width="18" height="12" rx="2"/><path d="M8 11h2"/></svg>';
        }
        if (key.indexOf("toy") !== -1) {
            return '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="12" cy="12" r="7"/><path d="M9 12h6M12 9v6"/></svg>';
        }
        return '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M4 7h16l-2 12H6z"/><path d="M9 7V5a3 3 0 0 1 6 0v2"/></svg>';
    }

    function uniqueValues(items, key) {
        var seen = {};
        var result = [];
        for (var i = 0; i < items.length; i++) {
            var v = items[i][key];
            if (v && !seen[v]) { seen[v] = true; result.push(v); }
        }
        result.sort();
        return result;
    }

    function populateSelect(selectId, values, allLabel) {
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
            opt.textContent = values[i];
            select.appendChild(opt);
        }
    }

    function applyFilters() {
        var query = state.query.trim().toLowerCase();
        var filtered = products.filter(function (product) {
            if (state.category && (product.category || "") !== state.category) return false;
            if (state.status && (product.status || "") !== state.status) return false;
            if (query) {
                var haystack = (product.name || "") + " " + (product.brand || "") + " " + (product.description || "");
                if (haystack.toLowerCase().indexOf(query) === -1) return false;
            }
            return true;
        });
        if (state.sort === "asc" || state.sort === "desc") {
            filtered.sort(function (a, b) {
                var av = (a.current_price === null || a.current_price === undefined) ? null : Number(a.current_price);
                var bv = (b.current_price === null || b.current_price === undefined) ? null : Number(b.current_price);
                if (av === null && bv === null) return 0;
                if (av === null) return 1;
                if (bv === null) return -1;
                return state.sort === "asc" ? av - bv : bv - av;
            });
        }
        return filtered;
    }

    function cardMarkup(product) {
        var visual = visualFor(product);
        var currentPrice = formatMoney(product.current_price, product.currency);
        var originalPrice = product.original_price !== null && product.original_price !== undefined ? formatMoney(product.original_price, product.currency) : "";
        var selected = product.product_id === state.selectedId ? " selected" : "";
        var gradient = "linear-gradient(135deg, " + visual.palette.start + " 0%, " + visual.palette.end + " 100%)";
        var categoryLine = product.category ? '<div class="category">' + escapeHtml(product.category) + '</div>' : '';
        var originalLine = originalPrice ? '<span class="price-original">' + escapeHtml(originalPrice) + '</span>' : '';
        return '' +
            '<article class="product-card' + selected + '" data-id="' + escapeHtml(product.product_id) + '" tabindex="0" role="button" aria-label="Select ' + escapeHtml(product.name || product.product_id) + '">' +
            '<div class="visual" style="background:' + gradient + '; color:' + visual.palette.ink + ';">' +
            escapeHtml(visual.letter) +
            iconMarkup(product.category) +
            '</div>' +
            '<div class="body">' +
            '<div class="name">' + escapeHtml(product.name || product.product_id) + '</div>' +
            '<div class="price-row">' +
            '<span class="price-current">' + escapeHtml(currentPrice) + '</span>' +
            originalLine +
            '</div>' +
            categoryLine +
            '<span class="badge" data-status="' + escapeHtml(product.status || "UNEXPECTED_ERROR") + '">' + escapeHtml(product.status || "UNEXPECTED_ERROR") + '</span>' +
            '</div>' +
            '</article>';
    }

    function renderProducts() {
        var grid = document.getElementById("product-grid");
        if (!grid) return;
        var filtered = applyFilters();
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

    function fieldRow(label, value, options) {
        options = options || {};
        var content;
        if (value === null || value === undefined || value === "") {
            content = '<span class="val muted">—</span>';
        } else if (options.mono) {
            content = '<pre>' + escapeHtml(value) + '</pre>';
        } else if (options.link) {
            content = '<a class="val" href="' + escapeHtml(value) + '" target="_blank" rel="noopener noreferrer">' + escapeHtml(value) + '</a>';
        } else {
            content = '<span class="val">' + escapeHtml(value) + '</span>';
        }
        return '<div class="row"><span class="key">' + escapeHtml(label) + '</span>' + content + '</div>';
    }

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
        var rows = [
            fieldRow("Name", product.name),
            fieldRow("Description", product.description),
            fieldRow("Category", product.category),
            fieldRow("Brand", product.brand),
            fieldRow("Current price", formatMoney(product.current_price, product.currency)),
            fieldRow("Original price", product.original_price !== null && product.original_price !== undefined ? formatMoney(product.original_price, product.currency) : null),
            fieldRow("Currency", product.currency),
            fieldRow("Variants", product.variant_count !== undefined && product.variant_count !== null ? product.variant_count : 0),
            fieldRow("Status", product.status),
            fieldRow("Collected at", product.collected_at),
            fieldRow("Product ID", product.product_id, { mono: true }),
            fieldRow("Primary image URL", product.primary_image_url, { mono: true }),
            fieldRow("Error", product.error_message),
            fieldRow("Source URL", product.product_url, { link: true })
        ];
        for (var r = 0; r < rows.length; r++) {
            var div = document.createElement("div");
            div.innerHTML = rows[r];
            panel.appendChild(div.firstChild);
        }
    }

    function selectProduct(productId) {
        state.selectedId = productId;
        var match = null;
        for (var i = 0; i < products.length; i++) {
            if (products[i].product_id === productId) { match = products[i]; break; }
        }
        renderEvidence(match);
        var cards = document.querySelectorAll(".product-card");
        for (var j = 0; j < cards.length; j++) {
            var card = cards[j];
            if (card.getAttribute("data-id") === productId) {
                card.classList.add("selected");
            } else {
                card.classList.remove("selected");
            }
        }
    }

    function renderSummary() {
        var total = document.getElementById("summary-total");
        var success = document.getElementById("summary-success");
        var partial = document.getElementById("summary-partial");
        var failed = document.getElementById("summary-failed");
        var generated = document.getElementById("summary-generated");
        if (total) total.textContent = summary.total !== undefined ? summary.total : products.length;
        if (success) success.textContent = summary.success !== undefined ? summary.success : 0;
        if (partial) partial.textContent = summary.partial !== undefined ? summary.partial : 0;
        if (failed) failed.textContent = summary.failed !== undefined ? summary.failed : 0;
        if (generated) generated.textContent = generatedAt || "—";
    }

    function attachControls() {
        var search = document.getElementById("search");
        var categoryFilter = document.getElementById("category-filter");
        var statusFilter = document.getElementById("status-filter");
        var priceSort = document.getElementById("price-sort");
        if (search) {
            search.addEventListener("input", function () {
                state.query = search.value;
                renderProducts();
            });
        }
        if (categoryFilter) {
            categoryFilter.addEventListener("change", function () {
                state.category = categoryFilter.value;
                renderProducts();
            });
        }
        if (statusFilter) {
            statusFilter.addEventListener("change", function () {
                state.status = statusFilter.value;
                renderProducts();
            });
        }
        if (priceSort) {
            priceSort.addEventListener("change", function () {
                state.sort = priceSort.value;
                renderProducts();
            });
        }
    }

    function init() {
        populateSelect("category-filter", uniqueValues(products, "category"), "All categories");
        populateSelect("status-filter", uniqueValues(products, "status"), "All statuses");
        renderSummary();
        renderProducts();
        attachControls();
        if (products.length > 0) {
            selectProduct(products[0].product_id);
        }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
</script>
</body>
</html>
"""


def render_gallery(collection: ProductCollection) -> str:
    embedded = (
        json.dumps(product_payload(collection), ensure_ascii=False)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )
    summary = collection.summary
    generated_label = collection.generated_at or "—"
    return (
        _TEMPLATE
        .replace("__EMBEDDED_DATA__", embedded)
        .replace("__TOTAL__", str(summary.total))
        .replace("__SUCCESS__", str(summary.success))
        .replace("__PARTIAL__", str(summary.partial))
        .replace("__FAILED__", str(summary.failed))
        .replace("__GENERATED__", html.escape(generated_label))
    )


__all__ = ["render_gallery"]
