#!/usr/bin/env python3
"""
Generate index.html from Stationpedia extractor output.

Usage:
    python3 generate.py --stationpedia Stationpedia.json --enums Enums.json
"""

import argparse
import html
import json
import re
import sys
from pathlib import Path

OUTPUT = Path(__file__).parent / "index.html"


def strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "")


def load_data(stationpedia_path: Path, enums_path: Path) -> dict:
    with open(stationpedia_path) as f:
        sp = json.load(f)
    with open(enums_path) as f:
        en = json.load(f)

    devices = []
    for page in sp["pages"]:
        logic = sorted(
            [
                {
                    "name": strip_tags(li["LogicName"]),
                    "access": li["LogicAccessTypes"],
                }
                for li in page["LogicInsert"]
            ],
            key=lambda x: x["name"],
        )
        slot_logic = sorted(
            [
                {
                    "name": strip_tags(li["LogicName"]),
                    "slots": li["LogicAccessTypes"],
                }
                for li in page["LogicSlotInsert"]
            ],
            key=lambda x: x["name"],
        )
        if not logic and not slot_logic:
            continue
        devices.append({
            "name": page["PrefabName"],
            "hash": page["PrefabHash"],
            "logic": logic,
            "slot_logic": slot_logic,
        })
    devices.sort(key=lambda d: d["name"])

    instructions = sorted(
        [
            {
                "op": op,
                "desc": strip_tags(info.get("desc", "")),
                "example": strip_tags(info.get("example", "")),
            }
            for op, info in sp["scriptCommands"].items()
        ],
        key=lambda i: i["op"],
    )

    constants = sorted(
        [
            {
                "name": name,
                "value": info.get("value", ""),
                "desc": strip_tags(info.get("desc", "")),
            }
            for name, info in sp.get("scriptConstants", {}).items()
        ],
        key=lambda c: c["name"],
    )

    logic_types = sorted(en["scriptEnums"]["LogicType"]["values"].keys())
    slot_types = sorted(en["scriptEnums"]["LogicSlotType"]["values"].keys())

    # Every other enum, one table each. LogicType/LogicSlotType have their own
    # tab. Keys starting with "_" are unnamed in the export; fall back to
    # enumName. The most-used ones for IC10 are pinned first.
    seen = {"LogicType", "LogicSlotType"}
    enums = []
    for group in ("scriptEnums", "basicEnums"):
        for key, info in en[group].items():
            name = info["enumName"] if key.startswith("_") else key
            if name in seen:
                continue
            seen.add(name)
            values = sorted(
                [
                    {"name": n, "value": v["value"], "deprecated": v.get("deprecated", False)}
                    for n, v in info["values"].items()
                ],
                key=lambda x: x["value"],
            )
            enums.append({"name": name, "values": values})
    link_enum_usage(enums, sp, en)
    pinned = ["DisplayMode", "Color", "LogicBatchMethod", "LogicReagentMode"]
    enums.sort(key=lambda x: (pinned.index(x["name"]) if x["name"] in pinned else len(pinned), x["name"]))

    return {
        "devices": devices,
        "instructions": instructions,
        "constants": constants,
        "logic_types": logic_types,
        "slot_types": slot_types,
        "enums": enums,
        "version": sp.get("version", "unknown"),
    }


def link_enum_usage(enums: list, sp: dict, en: dict) -> None:
    """Attach a "uses" list to each enum, from exact links in the export only.

    Matching enum value names against arbitrary strings gives false positives
    ("None", "Default" are everywhere), so only these structural links count:
    a device's whole Mode list, a LogicType/LogicSlotType named after the enum
    (or an item field of that name whose values all come from the enum), and
    instruction text listing at least two of the enum's "Name (value)" pairs.
    """
    logic_types = set(en["scriptEnums"]["LogicType"]["values"])
    slot_types = set(en["scriptEnums"]["LogicSlotType"]["values"])

    # Item fields whose values all come from one enum, e.g. Item.FilterType
    # holds GasType names. Keyed by field name.
    item_values = {}
    for page in sp["pages"]:
        for field, value in (page.get("Item") or {}).items():
            if isinstance(value, str):
                item_values.setdefault(field, set()).add(value)

    for en_ in enums:
        values = {v["name"]: v["value"] for v in en_["values"]}
        name = en_["name"]
        uses = []

        pairs = [f'{n} ({v})' for n, v in values.items()]
        ops = sorted(
            op for op, info in sp["scriptCommands"].items()
            if sum(pair in strip_tags(info.get("desc", "")) for pair in pairs) >= 2
        )
        if ops:
            uses.append({"label": "Instructions", "items": ops})

        mode_devices = []
        for page in sp["pages"]:
            modes = {
                strip_tags(m["LogicName"]): m["LogicAccessTypes"]
                for m in page.get("ModeInsert") or []
            }
            if modes and all(str(values.get(k)) == v for k, v in modes.items()):
                mode_devices.append(page["PrefabName"])
        if mode_devices:
            uses.append({"label": "Mode on", "items": sorted(set(mode_devices))})

        def pages_with(insert: str, logic_name: str) -> list:
            return sorted({
                page["PrefabName"] for page in sp["pages"]
                if any(strip_tags(li["LogicName"]) == logic_name for li in page[insert])
            })

        if name in logic_types:
            uses.append({"label": f"{name} logic type on", "items": pages_with("LogicInsert", name)})
        for st in sorted(slot_types):
            vals = item_values.get(st)
            if st == name or (vals and vals <= values.keys()):
                uses.append({"label": f"{st} slot logic type on", "items": pages_with("LogicSlotInsert", st)})

        en_["uses"] = [u for u in uses if u["items"]]


def e(text) -> str:
    return html.escape(str(text))


def render_devices(devices: list) -> str:
    rows = []
    for d in devices:
        logic_cells = "".join(
            f'<tr><td>{e(li["name"])}</td>'
            f'<td class="access {li["access"].lower().replace(" ", "")}">{e(li["access"])}</td></tr>'
            for li in d["logic"]
        )
        slot_cells = "".join(
            f'<tr><td>{e(li["name"])}</td><td class="slots">{e(li["slots"])}</td></tr>'
            for li in d["slot_logic"]
        )
        logic_table = (
            f'<table><thead><tr><th>LogicType</th><th>Access</th></tr></thead>'
            f'<tbody>{logic_cells}</tbody></table>'
            if logic_cells else ""
        )
        slot_table = (
            f'<table><thead><tr><th>SlotLogicType</th><th>Slots</th></tr></thead>'
            f'<tbody>{slot_cells}</tbody></table>'
            if slot_cells else ""
        )
        param_names = " ".join(
            li["name"].lower() for li in d["logic"] + d["slot_logic"]
        )
        search_text = e(f'{d["name"].lower()} {param_names}')
        rows.append(
            f'<div class="device-card" data-search="{search_text}">'
            f'<div class="device-header">'
            f'<span class="device-name">{e(d["name"])}</span>'
            f'<span class="device-hash">{e(d["hash"])}</span>'
            f'</div>'
            f'<div class="device-tables">{logic_table}{slot_table}</div>'
            f'</div>'
        )
    return "\n".join(rows)


def render_instructions(instructions: list) -> str:
    rows = []
    for i in instructions:
        rows.append(
            f'<div class="instr-row" data-search="{e(i["op"].lower())}">'
            f'<code class="op">{e(i["op"])}</code>'
            f'<div class="instr-detail">'
            f'<div class="instr-example"><code>{e(i["example"])}</code></div>'
            f'<div class="instr-desc">{e(i["desc"])}</div>'
            f'</div>'
            f'</div>'
        )
    return "\n".join(rows)


def render_constants(constants: list) -> str:
    rows = []
    for c in constants:
        rows.append(
            f'<tr data-search="{e(c["name"].lower())}">'
            f'<td><code>{e(c["name"])}</code></td>'
            f'<td><code>{e(c["value"])}</code></td>'
            f'<td>{e(c["desc"])}</td>'
            f'</tr>'
        )
    return "\n".join(rows)


def render_logic_types(logic_types: list, slot_types: list) -> str:
    lt = "".join(f'<span class="tag">{e(t)}</span>' for t in logic_types)
    st = "".join(f'<span class="tag">{e(t)}</span>' for t in slot_types)
    return (
        f'<h2>LogicType <span class="count">({len(logic_types)})</span></h2>'
        f'<div class="tag-list">{lt}</div>'
        f'<h2>LogicSlotType <span class="count">({len(slot_types)})</span></h2>'
        f'<div class="tag-list">{st}</div>'
    )


def render_enums(enums: list) -> str:
    cards = []
    for en in enums:
        rows = "".join(
            f'<tr data-search="{e(v["name"].lower())}"'
            f'{" class=\"deprecated\"" if v["deprecated"] else ""}>'
            f'<td class="enum-value">{e(v["value"])}</td><td>{e(v["name"])}</td></tr>'
            for v in en["values"]
        )
        uses = ""
        for u in en["uses"]:
            items = ", ".join(e(i) for i in u["items"])
            label = f'{e(u["label"])} ({len(u["items"])})'
            uses += (
                f'<div class="enum-use"><span>{label}:</span> {items}</div>'
                if len(u["items"]) <= 6 else
                f'<details class="enum-use"><summary>{label}</summary>{items}</details>'
            )
        used_by = " ".join(i.lower() for u in en["uses"] for i in u["items"])
        cards.append(
            f'<div class="enum-card" data-search="{e(en["name"].lower())} {e(used_by)}">'
            f'<div class="device-header"><span class="device-name">{e(en["name"])}</span>'
            f'<span class="device-hash">{len(en["values"])}</span></div>'
            f'{f"<div class=\"enum-uses\">{uses}</div>" if uses else ""}'
            f'<table><tbody>{rows}</tbody></table>'
            f'</div>'
        )
    return "\n".join(cards)


CSS = """
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'Segoe UI', system-ui, sans-serif; background: #1a1a1a; color: #d0d0d0; line-height: 1.5; }
header { background: #111; border-bottom: 1px solid #333; padding: 1rem 2rem; display: flex; align-items: center; gap: 2rem; flex-wrap: wrap; }
header h1 { font-size: 1.2rem; color: #e8a020; white-space: nowrap; }
.version { font-size: 0.8rem; color: #666; }
nav { display: flex; gap: 0.5rem; }
nav button { background: #222; border: 1px solid #444; color: #aaa; padding: 0.4rem 1rem; border-radius: 4px; cursor: pointer; font-size: 0.9rem; }
nav button.active { background: #e8a020; color: #111; border-color: #e8a020; font-weight: 600; }
.search-wrap { flex: 1; min-width: 200px; }
#search { width: 100%; background: #222; border: 1px solid #444; color: #d0d0d0; padding: 0.4rem 0.8rem; border-radius: 4px; font-size: 0.9rem; }
#search:focus { outline: none; border-color: #e8a020; }
main { padding: 1.5rem 2rem; max-width: 1400px; margin: 0 auto; }
.tab { display: none; }
.tab.active { display: block; }
/* Devices */
.device-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(400px, 1fr)); gap: 1rem; }
.device-card { background: #222; border: 1px solid #333; border-radius: 6px; overflow: hidden; }
.device-card.hidden { display: none; }
.device-header { display: flex; justify-content: space-between; align-items: center; padding: 0.6rem 0.8rem; background: #2a2a2a; border-bottom: 1px solid #333; }
.device-name { font-weight: 600; color: #e8a020; font-size: 0.9rem; }
.device-hash { font-family: monospace; font-size: 0.75rem; color: #666; }
.device-tables { display: flex; gap: 0; flex-wrap: wrap; }
.device-tables table { flex: 1; min-width: 180px; border-collapse: collapse; font-size: 0.8rem; }
.device-tables table + table { border-left: 1px solid #333; }
.device-tables th { padding: 0.3rem 0.6rem; background: #1e1e1e; color: #888; font-weight: 500; text-align: left; font-size: 0.75rem; }
.device-tables td { padding: 0.25rem 0.6rem; border-top: 1px solid #2a2a2a; }
td.access { font-size: 0.75rem; white-space: nowrap; }
td.readwrite { color: #7ec8e3; }
td.read { color: #90d090; }
td.write { color: #e07070; }
td.slots { font-size: 0.7rem; color: #666; max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
/* Instructions */
.instr-list { display: flex; flex-direction: column; gap: 0.5rem; }
.instr-row { background: #222; border: 1px solid #333; border-radius: 6px; padding: 0.6rem 0.8rem; display: flex; gap: 1rem; align-items: flex-start; }
.instr-row.hidden { display: none; }
code.op { color: #e8a020; font-size: 1rem; min-width: 80px; padding-top: 0.1rem; }
.instr-detail { flex: 1; }
.instr-example code { color: #7ec8e3; font-size: 0.85rem; }
.instr-desc { color: #aaa; font-size: 0.85rem; margin-top: 0.2rem; }
/* Constants */
.const-table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
.const-table th { text-align: left; padding: 0.5rem 0.8rem; border-bottom: 1px solid #444; color: #888; }
.const-table td { padding: 0.4rem 0.8rem; border-bottom: 1px solid #2a2a2a; }
.const-table tr.hidden { display: none; }
.const-table code { color: #e8a020; }
/* Logic Types */
h2 { color: #e8a020; margin: 1.5rem 0 0.5rem; font-size: 1rem; }
h2:first-child { margin-top: 0; }
.count { color: #666; font-weight: normal; }
.tag-list { display: flex; flex-wrap: wrap; gap: 0.4rem; }
.tag { background: #2a2a2a; border: 1px solid #444; border-radius: 3px; padding: 0.15rem 0.5rem; font-size: 0.8rem; font-family: monospace; color: #b0b0b0; }
/* Enums */
.enum-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 1rem; align-items: start; }
.enum-card { background: #222; border: 1px solid #333; border-radius: 6px; overflow: hidden; }
.enum-card.hidden, .enum-card tr.hidden { display: none; }
.enum-card table { width: 100%; border-collapse: collapse; font-size: 0.8rem; }
.enum-card td { padding: 0.25rem 0.6rem; border-top: 1px solid #2a2a2a; }
td.enum-value { font-family: monospace; color: #7ec8e3; text-align: right; width: 3.5rem; }
.enum-uses { padding: 0.4rem 0.6rem; font-size: 0.72rem; color: #888; border-bottom: 1px solid #333; overflow-wrap: anywhere; }
.enum-use + .enum-use { margin-top: 0.25rem; }
.enum-use span, .enum-use summary { color: #aaa; }
.enum-use summary { cursor: pointer; }
.enum-card tr.deprecated td { color: #666; text-decoration: line-through; }
/* Tools */
.tool-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 1rem; align-items: start; }
.tool-card { background: #222; border: 1px solid #333; border-radius: 6px; overflow: hidden; }
.tool-card.hidden { display: none; }
.tool-body { display: flex; align-items: flex-end; gap: 0.6rem; padding: 0.8rem; }
.tool-body label { flex: 1; display: flex; flex-direction: column; gap: 0.2rem; font-size: 0.75rem; color: #888; }
.tool-body input { width: 100%; background: #1a1a1a; border: 1px solid #444; color: #7ec8e3; padding: 0.4rem 0.6rem; border-radius: 4px; font-family: monospace; font-size: 1rem; }
.tool-body input:focus { outline: none; border-color: #e8a020; }
.tool-sep { color: #666; padding-bottom: 0.45rem; }
.no-results { color: #666; padding: 2rem; text-align: center; display: none; }
"""

JS = """
const tabs = document.querySelectorAll('nav button');
const panels = document.querySelectorAll('.tab');
const searchInput = document.getElementById('search');

tabs.forEach(btn => {
    btn.addEventListener('click', () => {
        tabs.forEach(b => b.classList.remove('active'));
        panels.forEach(p => p.classList.remove('active'));
        btn.classList.add('active');
        document.getElementById(btn.dataset.tab).classList.add('active');
        searchInput.value = '';
        filterAll('');
    });
});

searchInput.addEventListener('input', () => filterAll(searchInput.value.toLowerCase().trim()));

function filterAll(q) {
    const activeTab = document.querySelector('.tab.active').id;
    if (activeTab === 'tab-devices') {
        document.querySelectorAll('.device-card').forEach(el => {
            el.classList.toggle('hidden', q && !el.dataset.search.includes(q));
        });
    } else if (activeTab === 'tab-instructions') {
        document.querySelectorAll('.instr-row').forEach(el => {
            el.classList.toggle('hidden', q && !el.dataset.search.includes(q));
        });
    } else if (activeTab === 'tab-constants') {
        document.querySelectorAll('.const-table tr[data-search]').forEach(el => {
            el.classList.toggle('hidden', q && !el.dataset.search.includes(q));
        });
    } else if (activeTab === 'tab-enums') {
        // Enum name match shows the whole table; otherwise show matching values only.
        document.querySelectorAll('.enum-card').forEach(card => {
            const nameHit = !q || card.dataset.search.includes(q);
            let anyRow = false;
            card.querySelectorAll('tr[data-search]').forEach(tr => {
                const hit = nameHit || tr.dataset.search.includes(q);
                tr.classList.toggle('hidden', !hit);
                anyRow = anyRow || hit;
            });
            card.classList.toggle('hidden', !anyRow);
        });
    } else if (activeTab === 'tab-tools') {
        document.querySelectorAll('.tool-card').forEach(el => {
            el.classList.toggle('hidden', q && !el.dataset.search.includes(q));
        });
    }
}

// Tools: editing one field recalculates the other. Rounded to 4 places to
// hide float noise from the 273.15 offset (e.g. 0.15000000000003).
function linkFields(a, b, aToB, bToA) {
    const fmt = v => String(Math.round(v * 1e4) / 1e4);
    const wire = (src, dst, fn) => src.addEventListener('input', () => {
        const v = parseFloat(src.value);
        dst.value = Number.isFinite(v) ? fmt(fn(v)) : '';
    });
    wire(a, b, aToB);
    wire(b, a, bToA);
}
linkFields(document.getElementById('tool-kelvin'), document.getElementById('tool-celsius'),
    k => k - 273.15, c => c + 273.15);
"""


# Static, not derived from the export. Each card's inputs are wired up in JS.
TOOLS_HTML = """
<div class="tool-card" data-search="temperature kelvin celsius converter">
  <div class="device-header"><span class="device-name">Temperature</span></div>
  <div class="tool-body">
    <label>Kelvin<input id="tool-kelvin" type="number" step="any" value="293.15"></label>
    <span class="tool-sep">&harr;</span>
    <label>Celsius<input id="tool-celsius" type="number" step="any" value="20"></label>
  </div>
</div>
"""


def generate(data: dict) -> str:
    version = data["version"]
    devices_html = render_devices(data["devices"])
    instructions_html = render_instructions(data["instructions"])
    constants_html = render_constants(data["constants"])
    logic_html = render_logic_types(data["logic_types"], data["slot_types"])
    enums_html = render_enums(data["enums"])

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Stationpedia Reference</title>
<style>{CSS}</style>
</head>
<body>
<header>
  <h1>Stationpedia Reference</h1>
  <span class="version">game v{e(version)}</span>
  <nav>
    <button class="active" data-tab="tab-devices">Devices ({len(data["devices"])})</button>
    <button data-tab="tab-instructions">Instructions ({len(data["instructions"])})</button>
    <button data-tab="tab-constants">Constants ({len(data["constants"])})</button>
    <button data-tab="tab-logic">Logic Types</button>
    <button data-tab="tab-enums">Enums ({len(data["enums"])})</button>
    <button data-tab="tab-tools">Tools</button>
  </nav>
  <div class="search-wrap"><input id="search" type="search" placeholder="Filter…"></div>
</header>
<main>
  <div id="tab-devices" class="tab active">
    <div class="device-grid">{devices_html}</div>
  </div>
  <div id="tab-instructions" class="tab">
    <div class="instr-list">{instructions_html}</div>
  </div>
  <div id="tab-constants" class="tab">
    <table class="const-table">
      <thead><tr><th>Name</th><th>Value</th><th>Description</th></tr></thead>
      <tbody>{constants_html}</tbody>
    </table>
  </div>
  <div id="tab-logic" class="tab">{logic_html}</div>
  <div id="tab-enums" class="tab">
    <div class="enum-grid">{enums_html}</div>
  </div>
  <div id="tab-tools" class="tab">
    <div class="tool-grid">{TOOLS_HTML}</div>
  </div>
</main>
<script>{JS}</script>
</body>
</html>"""


def main():
    parser = argparse.ArgumentParser(description="Generate Stationpedia reference site")
    parser.add_argument("--stationpedia", required=True, type=Path, help="Path to Stationpedia.json")
    parser.add_argument("--enums", required=True, type=Path, help="Path to Enums.json")
    args = parser.parse_args()

    for p in (args.stationpedia, args.enums):
        if not p.exists():
            print(f"Error: {p} not found", file=sys.stderr)
            sys.exit(1)

    data = load_data(args.stationpedia, args.enums)
    html_out = generate(data)
    OUTPUT.write_text(html_out, encoding="utf-8")

    print(f"Generated {OUTPUT}")
    print(f"  Devices with logic data: {len(data['devices'])}")
    print(f"  Instructions: {len(data['instructions'])}")
    print(f"  Constants: {len(data['constants'])}")
    print(f"  LogicTypes: {len(data['logic_types'])}, SlotTypes: {len(data['slot_types'])}")
    print(f"  Enums: {len(data['enums'])}")


if __name__ == "__main__":
    main()
