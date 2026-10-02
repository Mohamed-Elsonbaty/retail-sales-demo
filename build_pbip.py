"""Build the Power BI project (PBIP) for the synthetic retail demo.

Writes RetailDemo.pbip, RetailDemo.SemanticModel (TMDL) and RetailDemo.Report (PBIR)
next to this script. The model reads the CSVs made by generate_data.py from the
DataFolder parameter; change it in Power BI Desktop under Transform data > Edit
parameters if the files live somewhere else.

TMDL is written as UTF-8 without a BOM and with CRLF line endings: Power BI
Desktop will not load a model whose files start with a BOM.

    python build_pbip.py
"""
import json
import shutil
import uuid
from pathlib import Path

HERE = Path(__file__).parent
NAME = "RetailDemo"
SM = HERE / f"{NAME}.SemanticModel"
RP = HERE / f"{NAME}.Report"
DATA_FOLDER = str((HERE / "data").resolve()) + "\\"


def tag(*parts):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "retaildemo/" + "/".join(parts)))


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    text = text.replace("\r\n", "\n").replace("\n", "\r\n")
    path.write_bytes(text.encode("utf-8"))  # utf-8, no BOM


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


# =================================================================== semantic model
def q(name):
    return f"'{name}'" if any(c in name for c in " -%&()") else name


def column(table, name, dtype, fmt=None, hidden=False, summarize="none", sort_by=None, calc=False):
    lines = [f"\tcolumn {q(name)}", f"\t\tdataType: {dtype}"]
    if hidden:
        lines.append("\t\tisHidden")
    if fmt:
        lines.append(f"\t\tformatString: {fmt}")
    lines.append(f"\t\tlineageTag: {tag(table, name)}")
    lines.append(f"\t\tsummarizeBy: {summarize}")
    if calc:
        lines.append("\t\tisNameInferred")
    lines.append(f"\t\tsourceColumn: {'[' + name + ']' if calc else name}")
    if sort_by:
        lines.append(f"\t\tsortByColumn: {q(sort_by)}")
    lines += ["", "\t\tannotation SummarizationSetBy = Automatic", ""]
    return "\n".join(lines)


def csv_table(table, file, cols):
    """cols: list of (name, tmdl dataType, M type, format)."""
    types = ", ".join(f'{{"{n}", {m}}}' for n, _, m, _ in cols)
    out = [f"table {q(table)}", f"\tlineageTag: {tag(table)}", ""]
    for n, dt, _, fmt in cols:
        hidden = n.endswith("_id") and table not in ("Branch", "Product")
        out.append(column(table, n, dt, fmt, hidden=hidden))
    out += [
        f"\tpartition {q(table)} = m",
        "\t\tmode: import",
        "\t\tsource =",
        "\t\t\t\tlet",
        f'\t\t\t\t    Source = Csv.Document(File.Contents(DataFolder & "{file}"), [Delimiter=",", Encoding=65001, QuoteStyle=QuoteStyle.Csv]),',
        "\t\t\t\t    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),",
        f'\t\t\t\t    Typed = Table.TransformColumnTypes(Promoted, {{{types}}}, "en-US")',
        "\t\t\t\tin",
        "\t\t\t\t    Typed",
        "",
        "\tannotation PBI_ResultType = Table",
        "",
    ]
    return "\n".join(out)


TABLES = {
    "Sales": ("sales.csv", [
        ("date", "dateTime", "type date", "dd/MM/yyyy"),
        ("branch_id", "int64", "Int64.Type", "0"),
        ("product_id", "int64", "Int64.Type", "0"),
        ("qty", "int64", "Int64.Type", "#,0"),
        ("net_sales", "double", "type number", "#,0.00"),
        ("cost", "double", "type number", "#,0.00"),
        ("is_refund", "boolean", "type logical", None),
        ("channel", "string", "type text", None),
    ]),
    "Branch": ("branches.csv", [
        ("branch_id", "int64", "Int64.Type", "0"),
        ("branch_name", "string", "type text", None),
        ("area", "string", "type text", None),
        ("channel", "string", "type text", None),
        ("open_date", "dateTime", "type date", "dd/MM/yyyy"),
    ]),
    "Product": ("products.csv", [
        ("product_id", "int64", "Int64.Type", "0"),
        ("product_name", "string", "type text", None),
        ("category", "string", "type text", None),
        ("unit_price", "double", "type number", "#,0.00"),
        ("unit_cost", "double", "type number", "#,0.00"),
    ]),
    "Target": ("targets.csv", [
        ("month", "dateTime", "type date", "MMM yyyy"),
        ("branch_id", "int64", "Int64.Type", "0"),
        ("target", "double", "type number", "#,0"),
    ]),
}

DATE_TABLE = """table Date
	lineageTag: {t}
	dataCategory: Time

{cols}
	partition Date = calculated
		mode: import
		source =
				ADDCOLUMNS(
				    CALENDAR(DATE(2024, 1, 1), MAX(Sales[date])),
				    "Year", YEAR([Date]),
				    "Month Number", MONTH([Date]),
				    "Month", FORMAT([Date], "MMM"),
				    "Year Month", FORMAT([Date], "YYYY-MM"),
				    "Quarter", "Q" & QUARTER([Date])
				)

	annotation PBI_ResultType = Table
"""

# name: (expression, format, folder, description)
MEASURES = [
    ("Net Sales", "SUM(Sales[net_sales])", "#,0", "Sales",
     "Sales after discounts and returns."),
    ("Cost", "SUM(Sales[cost])", "#,0", "Sales", None),
    ("Gross Profit", "[Net Sales] - [Cost]", "#,0", "Sales", None),
    ("Gross Margin %", "DIVIDE([Gross Profit], [Net Sales])", "0.0%", "Sales", None),
    ("Units Sold", "CALCULATE(SUM(Sales[qty]), Sales[is_refund] = FALSE)", "#,0", "Sales", None),
    ("Gross Sales", "CALCULATE([Net Sales], Sales[is_refund] = FALSE)", "#,0", "Returns",
     "Sales before returns."),
    ("Returns Value", "-CALCULATE([Net Sales], Sales[is_refund] = TRUE)", "#,0", "Returns",
     "Value of returned goods, as a positive number."),
    ("Return Rate %", "DIVIDE([Returns Value], [Gross Sales])", "0.00%", "Returns", None),
    ("Net Sales LY", "CALCULATE([Net Sales], SAMEPERIODLASTYEAR('Date'[Date]))", "#,0", "Last Year",
     "Net sales for the same dates one year earlier."),
    ("vs LY %", "DIVIDE([Net Sales] - [Net Sales LY], [Net Sales LY])", "+0.0%;-0.0%;0.0%", "Last Year", None),
    ("LFL Net Sales", """
VAR PeriodStartLY = EDATE(MIN('Date'[Date]), -12)
RETURN
    CALCULATE(
        [Net Sales],
        KEEPFILTERS(FILTER(ALL(Branch[branch_id], Branch[open_date]), Branch[open_date] <= PeriodStartLY))
    )""", "#,0", "Last Year",
     "Net sales of branches that were already open at the start of the same period last year."),
    ("LFL Net Sales LY", """
VAR PeriodStartLY = EDATE(MIN('Date'[Date]), -12)
RETURN
    CALCULATE(
        [Net Sales LY],
        KEEPFILTERS(FILTER(ALL(Branch[branch_id], Branch[open_date]), Branch[open_date] <= PeriodStartLY))
    )""", "#,0", "Last Year", None),
    ("LFL %", "DIVIDE([LFL Net Sales] - [LFL Net Sales LY], [LFL Net Sales LY])", "+0.0%;-0.0%;0.0%", "Last Year",
     "Like-for-like growth: same branches, same period, this year vs last year."),
    ("Target", "SUM(Target[target])", "#,0", "Target",
     "Monthly branch target. Targets are set per branch, not per product or category."),
    ("Target Achievement %", "DIVIDE([Net Sales], [Target])", "0.0%", "Target", None),
    ("Achievement Status", """
VAR A = [Target Achievement %]
RETURN
    SWITCH(TRUE(), ISBLANK(A), BLANK(), A < 0.8, "Below 80%", A < 0.9, "80-90%", "90%+")""", None, "Target", None),
    ("Achievement Color", """
VAR A = [Target Achievement %]
RETURN
    SWITCH(TRUE(), ISBLANK(A), BLANK(), A < 0.8, "#C53030", A < 0.9, "#B7791F", "#1F8A5B")""", None, "Target",
     "Font colour for achievement: red below 80%, amber 80-90%, green 90% and above."),
    ("Branches Below 80%", """
COUNTROWS(
    FILTER(VALUES(Branch[branch_id]), NOT ISBLANK([Target]) && [Target Achievement %] < 0.8)
)""", "0", "Target", "How many branches are below 80% of target in the selected period."),
    ("Branch Count", "COUNTROWS(FILTER(VALUES(Branch[branch_id]), NOT ISBLANK([Net Sales])))", "0", "Target",
     "Branches with sales in the selected period."),
    ("vs LY Color", """
SWITCH(TRUE(), ISBLANK([Net Sales]), BLANK(), DIVIDE([Net Sales LY], [Net Sales]) < 0.5, "#6B7280",
    [vs LY %] >= 0, "#15803D", "#B91C1C")""", None, "Formatting",
     "Green when above last year, red when below."),
    ("LFL Color", 'IF(ISBLANK([LFL %]), BLANK(), IF([LFL %] >= 0, "#1F8A5B", "#C53030"))', None, "Formatting", None),
    ("Achievement Tint", """
VAR A = [Target Achievement %]
RETURN
    SWITCH(TRUE(), ISBLANK(A), BLANK(), A < 0.8, "#FDECEC", A < 0.9, "#FDF4E3", "#E7F5EE")""", None, "Formatting",
     "Light background behind the achievement value."),
    ("Trend Title", """
VAR Y = MAX('Date'[Year])
RETURN "Net sales by month, " & Y & " vs " & (Y - 1)""", None, "Titles", "Dynamic title for the monthly trend chart."),
    ("vs LY Label", """
VAR G = [vs LY %]
VAR IsNew = DIVIDE([Net Sales LY], [Net Sales]) < 0.5
RETURN
    SWITCH(TRUE(), ISBLANK([Net Sales]), BLANK(), IsNew, "new", IF(G >= 0, "▲ ", "▼ ") & FORMAT(ABS(G), "0.0%"))""", None, "Labels",
     "Arrow and growth vs last year, for cards and tables."),
    ("Target Gap Label", """
VAR A = [Target Achievement %]
RETURN IF(ISBLANK(A), BLANK(), IF(A >= 1, "▲ ", "▼ ") & FORMAT(ABS(A - 1) * 100, "0.0") & " pts")""", None, "Labels",
     "Percentage points above or below 100% of target."),
    ("Target Gap Color", 'IF(ISBLANK([Target Achievement %]), BLANK(), IF([Target Achievement %] >= 1, "#15803D", "#B91C1C"))',
     None, "Formatting", None),
    ("LFL Branch Count", """
VAR PeriodStartLY = EDATE(MIN('Date'[Date]), -12)
RETURN
    COUNTROWS(
        FILTER(VALUES(Branch[branch_id]),
            CALCULATE(MAX(Branch[open_date])) <= PeriodStartLY && NOT ISBLANK([Net Sales]))
    )""", "0", "Last Year", "Branches that count in like-for-like."),
    ("LFL vs LY %", """
VAR PeriodStartLY = EDATE(MIN('Date'[Date]), -12)
RETURN IF(CALCULATE(MAX(Branch[open_date])) <= PeriodStartLY, [vs LY %])""", "+0.0%;-0.0%;0.0%", "Last Year",
     "Growth vs last year, only for branches open all of last year (blank for new branches)."),
    ("LFL Branches Label", 'FORMAT([LFL Branch Count], "0") & " branches"', None, "Labels", None),
    ("Gross Profit Label", '"SAR " & FORMAT([Gross Profit] / 1000000, "0.0") & "M"', None, "Labels", None),
    ("Returns Label", '"SAR " & FORMAT([Returns Value] / 1000, "#,0") & "K"', None, "Labels", None),
    ("Target Label", '"SAR " & FORMAT([Target] / 1000000, "0.0") & "M"', None, "Labels", None),
    ("Below 80 Label", 'FORMAT([Branches Below 80%], "0") & " of " & FORMAT([Branch Count], "0")', None, "Labels", None),
    ("Below 80 Share Label", 'FORMAT(DIVIDE([Branches Below 80%], [Branch Count]), "0%") & " of branches"', None, "Labels", None),
    ("Best Branch", """
VAR T = ADDCOLUMNS(FILTER(VALUES(Branch[branch_name]), NOT ISBLANK([Target])), "@a", [Target Achievement %])
RETURN MAXX(TOPN(1, T, [@a], DESC), Branch[branch_name])""", None, "Target", "Branch with the highest target achievement."),
    ("Best Branch Achievement", """
VAR T = ADDCOLUMNS(FILTER(VALUES(Branch[branch_name]), NOT ISBLANK([Target])), "@a", [Target Achievement %])
RETURN FORMAT(MAXX(TOPN(1, T, [@a], DESC), [@a]), "0.0%")""", None, "Labels", None),
    ("Lowest Branch", """
VAR T = ADDCOLUMNS(FILTER(VALUES(Branch[branch_name]), NOT ISBLANK([Target])), "@a", [Target Achievement %])
RETURN MAXX(TOPN(1, T, [@a], ASC), Branch[branch_name])""", None, "Target", "Branch with the lowest target achievement."),
    ("Lowest Branch Achievement", """
VAR T = ADDCOLUMNS(FILTER(VALUES(Branch[branch_name]), NOT ISBLANK([Target])), "@a", [Target Achievement %])
RETURN FORMAT(MINX(TOPN(1, T, [@a], ASC), [@a]), "0.0%")""", None, "Labels", None),
    ("Headline Overview", """
"SAR " & FORMAT([Net Sales] / 1000000, "0.0") & "M net sales, " & FORMAT([vs LY %], "+0.0%;-0.0%")
    & " vs last year, " & FORMAT([Target Achievement %], "0.0%") & " of target\"""", None, "Titles",
     "Page headline that updates with the filters."),
    ("Headline Branches", """
FORMAT([Branches Below 80%], "0") & " of " & FORMAT([Branch Count], "0")
    & " branches are below 80% of target\"""", None, "Titles", "Page headline for the branch page."),
]


def measures_table():
    out = ["table _Measures", f"\tlineageTag: {tag('_Measures')}", ""]
    for name, expr, fmt, folder, desc in MEASURES:
        if desc:
            out.append(f"\t/// {desc}")
        if "\n" in expr.strip():
            out.append(f"\tmeasure {q(name)} =")
            out += ["\t\t\t" + ln for ln in expr.strip().split("\n")]
        else:
            out.append(f"\tmeasure {q(name)} = {expr}")
        if fmt:
            out.append(f"\t\tformatString: {fmt}")
        out.append(f"\t\tdisplayFolder: {folder}")
        out.append(f"\t\tlineageTag: {tag('_Measures', name)}")
        out.append("")
    out.append(column("_Measures", "Spacer", "int64", "0", hidden=True, calc=True))
    out += ["\tpartition _Measures = calculated", "\t\tmode: import", '\t\tsource = ROW("Spacer", 0)', "",
            "\tannotation PBI_ResultType = Table", ""]
    return "\n".join(out)


RELATIONSHIPS = [
    ("Sales", "date", "Date", "Date"),
    ("Sales", "branch_id", "Branch", "branch_id"),
    ("Sales", "product_id", "Product", "product_id"),
    ("Target", "month", "Date", "Date"),
    ("Target", "branch_id", "Branch", "branch_id"),
]


def build_model():
    if SM.exists():
        shutil.rmtree(SM)
    d = SM / "definition"
    write_json(SM / "definition.pbism", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/semanticModel/definitionProperties/1.0.0/schema.json",
        "version": "4.2", "settings": {}})
    write(d / "database.tmdl", "database\n\tcompatibilityLevel: 1606\n")
    order = ["DataFolder"] + list(TABLES)
    refs = "\n".join(f"ref table {q(t)}" for t in list(TABLES) + ["Date", "_Measures"])
    write(d / "model.tmdl", f"""model Model
	culture: en-US
	defaultPowerBIDataSourceVersion: powerBI_V3
	sourceQueryCulture: en-US
	dataAccessOptions
		legacyRedirects
		returnErrorValuesAsNull

annotation __PBI_TimeIntelligenceEnabled = 0

annotation PBI_QueryOrder = {json.dumps(order)}

{refs}
""")
    write(d / "expressions.tmdl", f"""/// Folder that holds branches.csv, products.csv, sales.csv and targets.csv (ends with a backslash).
expression DataFolder = "{DATA_FOLDER}" meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]
	lineageTag: {tag('DataFolder')}

	annotation PBI_ResultType = Text
""")
    for t, (file, cols) in TABLES.items():
        write(d / "tables" / f"{t}.tmdl", csv_table(t, file, cols))
    date_cols = "\n".join([
        column("Date", "Date", "dateTime", "dd/MM/yyyy", calc=True).replace("\t\tdataType: dateTime", "\t\tdataType: dateTime\n\t\tisKey"),
        column("Date", "Year", "int64", "0", calc=True),
        column("Date", "Month Number", "int64", "0", hidden=True, calc=True),
        column("Date", "Month", "string", sort_by="Month Number", calc=True),
        column("Date", "Year Month", "string", calc=True),
        column("Date", "Quarter", "string", calc=True),
    ])
    write(d / "tables" / "Date.tmdl", DATE_TABLE.format(t=tag("Date"), cols=date_cols))
    write(d / "tables" / "_Measures.tmdl", measures_table())
    rel = []
    for ft, fc, tt, tc in RELATIONSHIPS:
        rel += [f"relationship {tag('rel', ft, fc, tt)}", f"\tfromColumn: {q(ft)}.{q(fc)}",
                f"\ttoColumn: {q(tt)}.{q(tc)}", ""]
    write(d / "relationships.tmdl", "\n".join(rel))


# =================================================================== report (PBIR)
# Design B "Corporate Light": navy header with page tabs, a white filter bar, KPI cards
# with a coloured left edge, then the charts. Mockups in mockups/B-*.png.
VC = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.12.0/schema.json"
PAGE_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/2.1.0/schema.json"

NAVY, ACCENT, SKY = "#10213F", "#1D4ED8", "#60A5FA"
SEMI = "'Segoe UI Semibold', wf_segoe-ui_semibold, helvetica, arial, sans-serif"
BOLD = "'Segoe UI Bold', wf_segoe-ui_bold, helvetica, arial, sans-serif"
INK, MUTED, LINE, PAGE_BG, WHITE = "#111827", "#6B7280", "#E5E7EB", "#F4F6FA", "#FFFFFF"
LY_GREY, GOOD, BAD, AMBER = "#9CA3AF", "#15803D", "#B91C1C", "#B45309"
W, H = 1280, 720
PAD = 24


def L(v): return {"expr": {"Literal": {"Value": v}}}
def S(v): return L("'" + v + "'")
def B(v): return L("true" if v else "false")
def D(v): return L(f"{v}D")
def I(v): return L(f"{int(v)}L")
def solid(c): return {"solid": {"color": S(c)}}
def meas(m): return {"Measure": {"Expression": {"SourceRef": {"Entity": "_Measures"}}, "Property": m}}
def mcolor(m): return {"solid": {"color": {"expr": meas(m)}}}
def col(t, c): return {"Column": {"Expression": {"SourceRef": {"Entity": t}}, "Property": c}}
def pos(x, y, w, h, z): return {"x": x, "y": y, "z": z, "width": w, "height": h, "tabOrder": z}
def wild(ref): return {"data": [{"dataViewWildcard": {"matchingOption": 1}}], "metadata": ref}


def mf(m, label=None):
    d = {"field": meas(m), "queryRef": "_Measures." + m, "nativeQueryRef": label or m}
    if label:
        d["displayName"] = label
    return d


def cf(t, c, label=None, active=False):
    d = {"field": col(t, c), "queryRef": f"{t}.{c}", "nativeQueryRef": label or c}
    if label:
        d["displayName"] = label
    if active:
        d["active"] = True
    return d


NO_FRAME = {"background": [{"properties": {"show": B(False)}}], "border": [{"properties": {"show": B(False)}}],
            "title": [{"properties": {"show": B(False)}}], "visualHeader": [{"properties": {"show": B(False)}}],
            "dropShadow": [{"properties": {"show": B(False)}}]}


def panel_frame(title=None, title_measure=None, sub=None):
    o = {
        "background": [{"properties": {"show": B(True), "color": solid(WHITE), "transparency": D(0)}}],
        "border": [{"properties": {"show": B(True), "color": solid(LINE), "radius": D(10), "width": D(1)}}],
        "padding": [{"properties": {"top": D(12), "bottom": D(10), "left": D(16), "right": D(16)}}],
        "dropShadow": [{"properties": {"show": B(False)}}],
        "visualHeader": [{"properties": {"show": B(False)}}],
        "title": [{"properties": {"show": B(bool(title or title_measure)),
                                  "text": {"expr": meas(title_measure)} if title_measure else S(title or ""),
                                  "fontColor": solid(INK), "fontSize": D(12), "bold": B(False),
                                  "fontFamily": S(SEMI)}}],
    }
    if sub:
        o["subTitle"] = [{"properties": {"show": B(True), "text": S(sub), "fontColor": solid(MUTED), "fontSize": D(9)}}]
    return o


def visual(name, p, vtype, query=None, objects=None, vco=None, sort=None):
    v = {"visualType": vtype, "visualContainerObjects": vco if vco is not None else panel_frame(),
         "drillFilterOtherVisuals": True}
    if query:
        v["query"] = {"queryState": query}
        if sort:
            v["query"]["sortDefinition"] = {"sort": sort, "isDefaultSort": True}
    if objects:
        v["objects"] = objects
    return {"$schema": VC, "name": name, "position": p, "visual": v}


def shape(name, p, fill, radius=0, outline=None):
    return visual(name, p, "shape", objects={
        "shape": [{"properties": {"tileShape": S("rectangleRounded" if radius else "rectangle"),
                                  "rectangleRoundedCurve": I(radius)}}],
        "fill": [{"properties": {"fillColor": solid(fill), "transparency": D(0)}, "selector": {"id": "default"}}],
        "outline": [{"properties": {"show": B(bool(outline)), "lineColor": solid(outline or fill), "weight": I(1),
                                    "transparency": D(0)}, "selector": {"id": "default"}}],
    }, vco=NO_FRAME)


def textbox(name, p, paragraphs):
    """paragraphs: [[(text, size_pt, color, semibold)], ...]"""
    paras = [{"textRuns": [{"value": t, "textStyle": {"fontSize": f"{s}pt", "color": c,
                                                        "fontFamily": "Segoe UI Semibold" if b else "Segoe UI"}}
                           for t, s, c, b in para]} for para in paragraphs]
    return visual(name, p, "textbox", objects={"general": [{"properties": {"paragraphs": paras}}]}, vco=NO_FRAME)


# ---------------------------------------------------------------- shared chrome
def year_filter(year):
    return {"filter": {"Version": 2, "From": [{"Name": "d", "Entity": "Date", "Type": 0}],
                       "Where": [{"Condition": {"In": {
                           "Expressions": [{"Column": {"Expression": {"SourceRef": {"Source": "d"}}, "Property": "Year"}}],
                           "Values": [[{"Literal": {"Value": f"{year}L"}}]]}}}]}}


def slicer(name, p, table, column_, title, z, default_year=None):
    general = {"properties": {"selfFilterEnabled": B(True)}}
    if default_year:
        general["properties"]["filter"] = year_filter(default_year)
    return visual(name, pos(*p, z), "slicer", {"Values": {"projections": [cf(table, column_, title, active=True)]}}, objects={
        "data": [{"properties": {"mode": S("Dropdown")}}],
        "header": [{"properties": {"show": B(True), "text": S(title), "fontColor": solid(MUTED), "textSize": D(8),
                                   "fontFamily": S(SEMI)}}],
        "items": [{"properties": {"fontColor": solid(INK), "textSize": D(9)}}],
        "selection": [{"properties": {"singleSelect": B(bool(default_year)), "selectAllCheckboxEnabled": B(not default_year)}}],
        "general": [general],
    }, vco={**NO_FRAME, "padding": [{"properties": {"top": D(0), "bottom": D(0), "left": D(0), "right": D(0)}}]})


def chrome(prefix):
    vs = [
        shape(prefix + "hdrbg", pos(0, 0, W, 62, 0), NAVY),
        shape(prefix + "logo", pos(PAD, 14, 34, 34, 1), ACCENT, radius=8),
        textbox(prefix + "logoR", pos(PAD, 13, 34, 36, 2), [[("R", 14, WHITE, True)]]),
        textbox(prefix + "title", pos(PAD + 44, 8, 420, 50, 3), [
            [("Retail Sales Dashboard", 13, WHITE, True)],
            [("Synthetic demo data · to 30 Sep 2026", 8, "#9FB0CC", False)]]),
        visual(prefix + "nav", pos(W - PAD - 300, 12, 300, 40, 4), "pageNavigator", objects={
            "text": [{"properties": {"fontColor": solid("#9FB0CC"), "fontSize": D(10), "fontFamily": S(SEMI)},
                      "selector": {"id": "default"}},
                     {"properties": {"fontColor": solid(WHITE)}, "selector": {"id": "selected"}}],
            "fill": [{"properties": {"show": B(True), "fillColor": solid(NAVY), "transparency": D(0)}, "selector": {"id": "default"}},
                     {"properties": {"fillColor": solid("#1E3A66")}, "selector": {"id": "selected"}}],
            "outline": [{"properties": {"show": B(False)}, "selector": {"id": "default"}}],
            "shape": [{"properties": {"tileShape": S("rectangleRounded"), "rectangleRoundedCurve": I(6)}, "selector": {"id": "default"}}],
        }, vco=NO_FRAME),
        shape(prefix + "fltbg", pos(0, 62, W, 58, 5), WHITE),
        shape(prefix + "fltline", pos(0, 119, W, 1, 6), LINE),
        textbox(prefix + "fltlab", pos(PAD - 6, 76, 70, 30, 7), [[("Filters", 10, INK, True)]]),
    ]
    x, sw, g = 92, 150, 12
    for i, (t, c, label, dy) in enumerate([("Date", "Year", "Year", 2026), ("Date", "Month", "Month", None),
                                           ("Branch", "area", "Area", None), ("Branch", "channel", "Channel", None),
                                           ("Product", "category", "Category", None)]):
        vs.append(slicer(f"{prefix}sl{i}", (x + i * (sw + g), 68, sw, 48), t, c, label, 10 + i, dy))
    return vs


def kpi(prefix, i, x, y, w, h, value, label, ref, ref_title, bar, ref_color=None, units=None, value_size=18):
    """White card with a coloured left edge: label, value, and one comparison line."""
    name = f"{prefix}k{i}"
    mkey, fid = "_Measures." + value, "field-" + name
    value_props = [{"properties": {"horizontalAlignment": S("left"), "fontColor": solid(INK), "fontSize": D(value_size),
                                   "fontFamily": S(BOLD)}, "selector": {"id": "default"}}]
    if units:
        value_props.append({"properties": {"labelDisplayUnits": D(units), "labelPrecision": I(1)}, "selector": {"metadata": mkey}})
    card = visual(name, pos(x + 8, y + 2, w - 12, h - 4, 101 + i * 3), "cardVisual", {"Data": {"projections": [mf(value, label)]}}, objects={
        "label": [{"properties": {"show": B(True), "position": S("aboveValue"), "fontColor": solid(MUTED), "fontSize": D(9),
                                  "fontFamily": S(SEMI), "horizontalAlignment": S("left")},
                   "selector": {"id": "default"}}],
        "value": value_props,
        "referenceLabel": [
            {"properties": {"backgroundShow": B(False), "paddingUniform": I(0)}, "selector": {"id": "default"}},
            {"properties": {"value": {"expr": meas(ref)}},
             "selector": {"data": [{"dataViewWildcard": {"matchingOption": 0}}], "metadata": mkey, "id": fid, "order": 0}}],
        "referenceLabelTitle": [{"properties": {"titleContentType": S("custom"), "titleText": S(ref_title),
                                                "titleFontColor": solid(MUTED), "titleFontSize": D(9)},
                                 "selector": {"metadata": mkey, "id": fid}}],
        "referenceLabelValue": [{"properties": {"valueFontColor": mcolor(ref_color) if ref_color else solid(MUTED),
                                                "valueBold": B(True), "valueFontSize": D(9), "showBlankAs": L("''")},
                                 "selector": {"metadata": mkey, "id": fid}}],
        "referenceLabelLayout": [{"properties": {"horizontalAlignment": S("left"), "labelSpace": D(999),
                                                 "layout": S("horizontal")}, "selector": {"id": "default"}}],
        "layout": [{"properties": {"alignment": S("middle"), "columnCount": I(1), "style": S("Table")}}],
        "divider": [{"properties": {"show": B(False)}, "selector": {"id": "default"}}],
        "accentBar": [{"properties": {"show": B(False)}, "selector": {"id": "default"}}],
        "border": [{"properties": {"show": B(False)}, "selector": {"id": "default"}}],
        "outline": [{"properties": {"show": B(False)}, "selector": {"id": "default"}}],
    }, vco=NO_FRAME)
    return [
        shape(f"{prefix}k{i}bg", pos(x, y, w, h, 100 + i * 3), WHITE, radius=10, outline=LINE),
        shape(f"{prefix}k{i}bar", pos(x, y + 8, 4, h - 16, 102 + i * 3), bar),
        card,
    ]


AXES = {
    "categoryAxis": [{"properties": {"showAxisTitle": B(False), "labelColor": solid(MUTED), "fontSize": D(9), "gridlineShow": B(False)}}],
    "valueAxis": [{"properties": {"showAxisTitle": B(False), "labelColor": solid(MUTED), "fontSize": D(9),
                                  "gridlineColor": solid("#EEF0F4"), "gridlineStyle": S("solid"), "secShow": B(False)}}],
}


def table_objects(widths, extra_values=(), bars=()):
    o = {
        "columnHeaders": [{"properties": {"fontColor": solid(MUTED), "fontSize": D(8), "bold": B(True),
                                          "backColor": solid(WHITE), "fontFamily": S(SEMI), "wordWrap": B(False)}}],
        "values": [{"properties": {"fontSize": D(9), "fontColorPrimary": solid(INK), "backColorPrimary": solid(WHITE),
                                   "fontColorSecondary": solid(INK), "backColorSecondary": solid(WHITE)}}, *extra_values],
        "total": [{"properties": {"fontSize": D(9), "bold": B(True), "backColor": solid("#F9FAFB")}}],
        "grid": [{"properties": {"rowPadding": D(2), "gridVertical": B(False), "gridHorizontal": B(True),
                                 "gridHorizontalColor": solid("#F1F2F5"), "outlineColor": solid(LINE), "outlineWeight": D(1)}}],
        "columnWidth": [{"properties": {"value": D(w)}, "selector": {"metadata": ref}} for ref, w in widths],
    }
    if bars:
        o["columnFormatting"] = [{"properties": {"labelDisplayUnits": D(1000000), "labelPrecision": I(1), "dataBars": {
            "positiveColor": solid("#7C9BEA"), "negativeColor": solid(LINE), "axisColor": solid(WHITE),
            "reverseDirection": B(False), "hideText": B(False)}}, "selector": {"metadata": ref}} for ref in bars]
    return o


# ---------------------------------------------------------------- pages
def overview():
    p = "ov"
    vs = chrome(p)
    y, h, g = 130, 120, 12
    w = (W - 2 * PAD - 4 * g) / 5
    cards = [
        ("Net Sales", "NET SALES (SAR)", "vs LY Label", "vs last year", ACCENT, "vs LY Color", 1000000),
        ("Target Achievement %", "TARGET ACHIEVEMENT", "Target Gap Label", "to target", AMBER, "Target Gap Color", None),
        ("LFL %", "LIKE-FOR-LIKE", "LFL Branches Label", "same stores", BAD, None, None),
        ("Gross Margin %", "GROSS MARGIN", "Gross Profit Label", "gross profit", GOOD, None, None),
        ("Return Rate %", "RETURN RATE", "Returns Label", "returned", LY_GREY, None, None),
    ]
    for i, (m, label, ref, rt, bar, rc, units) in enumerate(cards):
        vs += kpi(p, i, PAD + i * (w + g), y, w, h, m, label, ref, rt, bar, rc, units)

    top = y + h + 12
    bottom = H - 16
    tw = 700
    vs.append(visual(p + "trend", pos(PAD, top, tw, bottom - top, 300), "lineClusteredColumnComboChart", {
        "Category": {"projections": [cf("Date", "Month", active=True)]},
        "Y": {"projections": [mf("Net Sales", "This year")]},
        "Y2": {"projections": [mf("Net Sales LY", "Last year")]},
    }, sort=[{"field": col("Date", "Month"), "direction": "Ascending"}], objects={
        **AXES,
        "dataPoint": [{"properties": {"fill": solid(ACCENT)}, "selector": {"metadata": "_Measures.Net Sales"}},
                      {"properties": {"fill": solid(LY_GREY)}, "selector": {"metadata": "_Measures.Net Sales LY"}}],
        "lineStyles": [{"properties": {"strokeWidth": I(2), "showMarker": B(True), "markerSize": I(3)}}],
        "legend": [{"properties": {"show": B(True), "position": S("TopRight"), "fontSize": D(9), "labelColor": solid(MUTED)}}],
    }, vco=panel_frame(title_measure="Trend Title", sub="Bars: this year · Line: last year · Ramadan moves about 11 days earlier each year")))

    rx, rw = PAD + tw + 12, W - PAD - (PAD + tw + 12)
    half = (bottom - top - 12) / 2
    vs.append(visual(p + "area", pos(rx, top, rw, half + 14, 301), "tableEx", {"Values": {"projections": [
        cf("Branch", "area", "Area"), mf("Net Sales", "Net sales"), mf("vs LY Label", "vs LY")]}},
        sort=[{"field": meas("Net Sales"), "direction": "Descending"}],
        objects=table_objects([("Branch.area", 130), ("_Measures.Net Sales", 250), ("_Measures.vs LY Label", 90)],
                              extra_values=[{"properties": {"fontColor": mcolor("vs LY Color")}, "selector": wild("_Measures.vs LY Label")}],
                              bars=["_Measures.Net Sales"]),
        vco=panel_frame("Area performance")))
    vs[-1]["visual"]["objects"]["total"] = [{"properties": {"totals": B(False)}}]

    vs.append(visual(p + "cat", pos(rx, top + half + 26, rw, half - 14, 302), "tableEx", {"Values": {"projections": [
        cf("Product", "category", "Category"), mf("Net Sales", "Net sales"), mf("Gross Margin %", "Margin")]}},
        sort=[{"field": meas("Net Sales"), "direction": "Descending"}],
        objects=table_objects([("Product.category", 130), ("_Measures.Net Sales", 250), ("_Measures.Gross Margin %", 90)],
                              bars=["_Measures.Net Sales"]),
        vco=panel_frame("Categories")))
    vs[-1]["visual"]["objects"]["total"] = [{"properties": {"totals": B(False)}}]
    return vs


def branches():
    p = "br"
    vs = chrome(p)
    y, h, g = 130, 120, 12
    w = (W - 2 * PAD - 3 * g) / 4
    cards = [
        ("Below 80 Label", "BRANCHES BELOW 80%", "Below 80 Share Label", "need action", BAD, None),
        ("Target Achievement %", "NETWORK ACHIEVEMENT", "Target Label", "target", AMBER, None),
        ("Best Branch", "BEST BRANCH", "Best Branch Achievement", "of target", GOOD, None),
        ("Lowest Branch", "LOWEST BRANCH", "Lowest Branch Achievement", "of target", BAD, None),
    ]
    for i, (m, label, ref, rt, bar, rc) in enumerate(cards):
        vs += kpi(p, i, PAD + i * (w + g), y, w, h, m, label, ref, rt, bar, rc)

    top, bottom = y + h + 12, H - 16
    sw = 560
    vs.append(visual(p + "scatter", pos(PAD, top, sw, bottom - top, 300), "scatterChart", {
        "Category": {"projections": [cf("Branch", "branch_name", "Branch", active=True)]},
        "X": {"projections": [mf("LFL vs LY %", "vs last year")]},
        "Y": {"projections": [mf("Target Achievement %", "Achievement")]},
        "Size": {"projections": [mf("Net Sales")]},
    }, objects={
        "categoryAxis": [{"properties": {"showAxisTitle": B(True), "titleText": S("Change vs last year"), "titleColor": solid(MUTED),
                                         "titleFontSize": D(9), "labelColor": solid(MUTED), "fontSize": D(9), "gridlineShow": B(False)}}],
        "valueAxis": [{"properties": {"showAxisTitle": B(True), "titleText": S("Target achievement"), "titleColor": solid(MUTED),
                                      "titleFontSize": D(9), "labelColor": solid(MUTED), "fontSize": D(9),
                                      "gridlineColor": solid("#EEF0F4")}}],
        "dataPoint": [{"properties": {"fill": mcolor("Achievement Color")},
                       "selector": {"data": [{"dataViewWildcard": {"matchingOption": 1}}]}}],
        "markers": [{"properties": {"transparency": D(25)}}],
        "categoryLabels": [{"properties": {"show": B(False)}}],
        "bubbles": [{"properties": {"bubbleSize": I(-20)}}],
        "y1AxisReferenceLine": [{"properties": {"show": B(True), "value": D(0.8), "lineColor": solid(BAD), "transparency": D(40),
                                                "style": S("dashed"), "displayName": S("80% of target"),
                                                "dataLabelShow": B(True), "dataLabelColor": solid(BAD),
                                                "dataLabelHorizontalPosition": S("right"), "dataLabelVerticalPosition": S("above"),
                                                "dataLabelDecoration": S("Name")}, "selector": {"id": "1"}}],
        "xAxisReferenceLine": [{"properties": {"show": B(True), "value": D(0), "lineColor": solid(LY_GREY), "transparency": D(20),
                                               "style": S("dashed")}, "selector": {"id": "2"}}],
    }, vco=panel_frame("Branch map: growth vs target",
                       sub="Each bubble is a branch, sized by net sales. Bottom-left needs attention first")))

    tx = PAD + sw + 12
    cols = [cf("Branch", "branch_name", "Branch"), cf("Branch", "area", "Area"), mf("Net Sales", "Net sales"),
            mf("vs LY Label", "vs LY"), mf("Target Achievement %", "Achievement")]
    vs.append(visual(p + "table", pos(tx, top, W - PAD - tx, bottom - top, 301), "tableEx", {"Values": {"projections": cols}},
                     sort=[{"field": meas("Target Achievement %"), "direction": "Ascending"}],
                     objects=table_objects(
                         [("Branch.branch_name", 170), ("Branch.area", 90), ("_Measures.Net Sales", 170),
                          ("_Measures.vs LY Label", 80), ("_Measures.Target Achievement %", 100)],
                         extra_values=[
                             {"properties": {"fontColor": mcolor("vs LY Color")}, "selector": wild("_Measures.vs LY Label")},
                             {"properties": {"fontColor": mcolor("Achievement Color"), "backColor": mcolor("Achievement Tint")},
                              "selector": wild("_Measures.Target Achievement %")}],
                         bars=["_Measures.Net Sales"]),
                     vco=panel_frame("Branches, lowest achievement first",
                                     sub="Achievement: red below 80%, amber 80–90%, green 90%+")))
    return vs


THEME = {
    "name": "RetailDemo",
    "dataColors": [ACCENT, LY_GREY, GOOD, BAD, AMBER, SKY, "#0F766E", "#7C3AED"],
    "foreground": INK, "foregroundNeutralSecondary": MUTED, "background": WHITE, "tableAccent": ACCENT,
    "good": GOOD, "bad": BAD, "neutral": AMBER,
    "textClasses": {
        "label": {"fontFace": "Segoe UI", "fontSize": 9, "color": MUTED},
        "title": {"fontFace": "Segoe UI Semibold", "fontSize": 12, "color": INK},
        "header": {"fontFace": "Segoe UI Semibold", "fontSize": 11, "color": INK},
        "callout": {"fontFace": "Segoe UI Bold", "fontSize": 20, "color": INK},
    },
}


def page(pid, title, visuals):
    pdir = RP / "definition" / "pages" / pid
    write_json(pdir / "page.json", {
        "$schema": PAGE_SCHEMA, "name": pid, "displayName": title, "displayOption": "FitToPage",
        "height": H, "width": W,
        "objects": {"background": [{"properties": {"color": solid(PAGE_BG), "transparency": D(0)}}],
                    "outspace": [{"properties": {"color": solid(PAGE_BG)}}]}})
    for v in visuals:
        write_json(pdir / "visuals" / v["name"] / "visual.json", v)


def build_report():
    if RP.exists():
        for child in RP.iterdir():               # keep Desktop's .pbi and .platform
            if child.name not in (".pbi", ".platform"):
                shutil.rmtree(child) if child.is_dir() else child.unlink()
    write_json(RP / "definition.pbir", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/2.0.0/schema.json",
        "version": "4.0", "datasetReference": {"byPath": {"path": f"../{NAME}.SemanticModel"}}})
    d = RP / "definition"
    write_json(d / "version.json", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/versionMetadata/1.0.0/schema.json",
        "version": "2.0.0"})
    theme_src = HERE / "theme" / "CY26SU05.json"
    base = RP / "StaticResources" / "SharedResources" / "BaseThemes" / "CY26SU05.json"
    base.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(theme_src, base)  # Microsoft's stock base theme
    write_json(RP / "StaticResources" / "RegisteredResources" / "RetailDemo.json", THEME)
    ver = {"visual": "2.9.0", "report": "3.3.0", "page": "2.3.1"}
    write_json(d / "report.json", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/report/3.3.0/schema.json",
        "themeCollection": {
            "baseTheme": {"name": "CY26SU05", "reportVersionAtImport": ver, "type": "SharedResources"},
            "customTheme": {"name": "RetailDemo.json", "reportVersionAtImport": ver, "type": "RegisteredResources"}},
        "resourcePackages": [
            {"name": "SharedResources", "type": "SharedResources",
             "items": [{"name": "CY26SU05", "path": "BaseThemes/CY26SU05.json", "type": "BaseTheme"}]},
            {"name": "RegisteredResources", "type": "RegisteredResources",
             "items": [{"name": "RetailDemo.json", "path": "RetailDemo.json", "type": "CustomTheme"}]}],
        "settings": {"useStylableVisualContainerHeader": True, "defaultDrillFilterOtherVisuals": True,
                     "allowChangeFilterTypes": True, "useEnhancedTooltips": True},
    })
    page("a1overview00000000001", "Overview", overview())
    page("b2branches00000000002", "Branches", branches())
    write_json(d / "pages" / "pages.json", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/pagesMetadata/1.1.0/schema.json",
        "pageOrder": ["a1overview00000000001", "b2branches00000000002"], "activePageName": "a1overview00000000001"})


def build_measures_only():
    """Rewrite _Measures.tmdl alone, so Desktop's loaded data (.pbi/cache.abf) is kept."""
    write(SM / "definition" / "tables" / "_Measures.tmdl", measures_table())


def build_pbip():
    write_json(HERE / f"{NAME}.pbip", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/pbip/pbipProperties/1.0.0/schema.json",
        "version": "1.0", "artifacts": [{"report": {"path": f"{NAME}.Report"}}],
        "settings": {"enableAutoRecovery": True}})
    write(HERE / ".gitignore", "**/.pbi/localSettings.json\n**/.pbi/cache.abf\n")


if __name__ == "__main__":
    import sys
    if "--report-only" in sys.argv:   # keep the loaded model and its data cache
        build_measures_only()
        build_report()
    else:
        build_model()
        build_report()
        build_pbip()
    print("written:", NAME + ".pbip")
