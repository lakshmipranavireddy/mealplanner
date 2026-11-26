"""
Meal Planner Notebook  -  SmartCommunity Hack, Project #35
Plan simple meals for a week and organise the ingredients into a grocery list.

Stack: Python 3.10+, FastHTML (web UI), JSON file storage, CSV/Markdown export,
Matplotlib charts. Run with:  python app.py   ->  http://localhost:5001
"""
import csv
import io
import json
import shutil
from collections import Counter
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # no GUI window; we only render PNG bytes
import matplotlib.pyplot as plt

from fasthtml.common import *
from starlette.datastructures import UploadFile
from starlette.responses import RedirectResponse, Response

# ----------------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------------
DATA_FILE = Path(__file__).parent / "meals.json"
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
MEAL_TYPES = ["Breakfast", "Lunch", "Dinner", "Snack"]
UNITS = ["g", "kg", "ml", "l", "pcs", "tbsp", "tsp", "cup"]
MAX_CAL = 3000          # validation limit for a single meal
HIGH_DAY_CAL = 2800     # daily warning thresholds
LOW_DAY_CAL = 1200


# ----------------------------------------------------------------------------
# Sample data (30+ realistic entries incl. boundary / edge cases)
# ----------------------------------------------------------------------------
def seed_data():
    breakfasts = [
        ("Oats with banana", 350, [("rolled oats", 60, "g"), ("banana", 1, "pcs"), ("milk", 200, "ml")]),
        ("Veg omelette", 300, [("eggs", 2, "pcs"), ("onion", 0.5, "pcs"), ("tomato", 1, "pcs")]),
        ("Poha", 320, [("poha", 80, "g"), ("peanuts", 20, "g"), ("onion", 0.5, "pcs")]),
        ("Idli with sambar", 380, [("idli batter", 200, "g"), ("toor dal", 40, "g"), ("carrot", 1, "pcs")]),
        ("Peanut butter toast", 340, [("bread", 2, "pcs"), ("peanut butter", 2, "tbsp"), ("banana", 1, "pcs")]),
        ("Upma", 310, [("semolina", 70, "g"), ("onion", 0.5, "pcs"), ("peas", 30, "g")]),
        ("Fruit and curd bowl", 280, [("curd", 150, "g"), ("apple", 1, "pcs"), ("honey", 1, "tsp")]),
    ]
    lunches = [
        ("Rajma rice", 600, [("rajma", 80, "g"), ("rice", 150, "g"), ("onion", 1, "pcs"), ("tomato", 2, "pcs")]),
        ("Veg pulao", 550, [("rice", 150, "g"), ("peas", 50, "g"), ("carrot", 1, "pcs"), ("onion", 1, "pcs")]),
        ("Dal and roti", 520, [("toor dal", 60, "g"), ("wheat flour", 100, "g"), ("tomato", 1, "pcs")]),
        ("Chicken curry and rice", 680, [("chicken", 200, "g"), ("rice", 150, "g"), ("onion", 1, "pcs"), ("tomato", 2, "pcs")]),
        ("Paneer wrap", 580, [("paneer", 100, "g"), ("wheat flour", 80, "g"), ("capsicum", 1, "pcs")]),
        ("Curd rice and pickle", 450, [("rice", 150, "g"), ("curd", 200, "g")]),
        ("Chole and rice", 640, [("chickpeas", 90, "g"), ("rice", 150, "g"), ("onion", 1, "pcs")]),
    ]
    dinners = [
        ("Vegetable khichdi", 500, [("rice", 80, "g"), ("moong dal", 60, "g"), ("carrot", 1, "pcs")]),
        ("Egg curry and roti", 560, [("eggs", 3, "pcs"), ("wheat flour", 100, "g"), ("tomato", 2, "pcs")]),
        ("Palak paneer and roti", 600, [("spinach", 200, "g"), ("paneer", 100, "g"), ("wheat flour", 100, "g")]),
        ("Grilled chicken salad", 450, [("chicken", 180, "g"), ("cucumber", 1, "pcs"), ("tomato", 1, "pcs")]),
        ("Veg noodles", 520, [("noodles", 120, "g"), ("capsicum", 1, "pcs"), ("carrot", 1, "pcs")]),
        ("Mixed veg curry and rice", 540, [("rice", 120, "g"), ("peas", 50, "g"), ("carrot", 1, "pcs"), ("onion", 1, "pcs")]),
        ("Sambar rice", 510, [("rice", 120, "g"), ("toor dal", 50, "g"), ("carrot", 1, "pcs")]),
    ]
    snacks = [
        ("Roasted peanuts", 180, [("peanuts", 30, "g")]),
        ("Apple slices", 95, [("apple", 1, "pcs")]),
        ("Sprouts chaat", 150, [("moong sprouts", 80, "g"), ("onion", 0.5, "pcs"), ("tomato", 1, "pcs")]),
        ("Buttermilk", 60, [("curd", 100, "g")]),
        ("Banana", 105, [("banana", 1, "pcs")]),
        ("Makhana", 120, [("makhana", 25, "g")]),
        ("Cucumber sticks", 40, [("cucumber", 1, "pcs")]),
    ]

    rows = []

    def add(day, mtype, name, cal, ings):
        rows.append({
            "day": day, "meal_type": mtype, "name": name, "calories": cal,
            "ingredients": [{"name": n, "qty": q, "unit": u} for n, q, u in ings],
        })

    for i, day in enumerate(DAYS):
        add(day, "Breakfast", *breakfasts[i])
        add(day, "Lunch", *lunches[i])
        if day != "Sunday":  # edge case: Sunday has no dinner -> "missing meal" warning
            add(day, "Dinner", *dinners[i])
        add(day, "Snack", *snacks[i])
    for i, day in enumerate(DAYS[:4]):  # second snack Mon-Thu
        add(day, "Snack", *snacks[(i + 3) % 7])
    add("Friday", "Snack", "Water with lemon", 0, [("lemon", 1, "pcs")])        # boundary: 0 kcal
    add("Saturday", "Dinner", "Party feast (biryani)", 1600,                     # edge: pushes day over limit
        [("rice", 250, "g"), ("chicken", 300, "g"), ("onion", 2, "pcs"), ("curd", 100, "g")])

    now = datetime.now().isoformat(timespec="seconds")
    for n, r in enumerate(rows, 1):
        r["id"] = n
        r["created"] = now
    return rows


# ----------------------------------------------------------------------------
# Persistence (JSON) with corrupted/missing file handling
# ----------------------------------------------------------------------------
def save_meals(meals):
    tmp = DATA_FILE.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(meals, f, indent=2, ensure_ascii=False)
    tmp.replace(DATA_FILE)  # atomic-ish write: never leaves a half-written file


def load_meals():
    try:
        with DATA_FILE.open(encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            raise ValueError("meals.json must contain a list")
        return data
    except FileNotFoundError:
        data = seed_data()
        save_meals(data)
        return data
    except (json.JSONDecodeError, ValueError):
        shutil.copy(DATA_FILE, DATA_FILE.with_suffix(".corrupt.bak"))  # keep the broken file
        save_meals([])
        return []


def next_id(meals):
    return max((m["id"] for m in meals), default=0) + 1


def sort_meals(meals):
    return sorted(meals, key=lambda m: (DAYS.index(m["day"]), MEAL_TYPES.index(m["meal_type"]), m["id"]))


# ----------------------------------------------------------------------------
# Validation
# ----------------------------------------------------------------------------
def parse_ingredients(text):
    """Parse lines of 'name, quantity, unit'. Returns (items, errors)."""
    items, errors = [], []
    for n, line in enumerate((text or "").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 3:
            errors.append(f"Ingredient line {n}: use the format 'name, quantity, unit'.")
            continue
        name, qty, unit = parts
        unit = unit.lower()
        if not (1 <= len(name) <= 40):
            errors.append(f"Ingredient line {n}: name must be 1-40 characters.")
            continue
        try:
            qty = float(qty)
        except ValueError:
            errors.append(f"Ingredient line {n}: quantity '{parts[1]}' is not a number.")
            continue
        if not (0 < qty <= 10000):
            errors.append(f"Ingredient line {n}: quantity must be between 0 and 10000.")
            continue
        if unit not in UNITS:
            errors.append(f"Ingredient line {n}: unit must be one of {', '.join(UNITS)}.")
            continue
        items.append({"name": name, "qty": qty, "unit": unit})
    return items, errors


def validate_meal(day, meal_type, name, calories, ingredients_text):
    """Returns (clean_dict or None, list_of_errors)."""
    errors = []
    day = (day or "").strip().title()
    meal_type = (meal_type or "").strip().title()
    name = (name or "").strip()

    if day not in DAYS:
        errors.append(f"Day must be one of: {', '.join(DAYS)}.")
    if meal_type not in MEAL_TYPES:
        errors.append(f"Meal type must be one of: {', '.join(MEAL_TYPES)}.")
    if not (2 <= len(name) <= 60):
        errors.append("Meal name must be 2-60 characters.")
    try:
        cal = int(str(calories).strip())
        if not (0 <= cal <= MAX_CAL):
            errors.append(f"Calories must be between 0 and {MAX_CAL}.")
    except ValueError:
        cal = None
        errors.append("Calories must be a whole number.")

    items, ing_errors = parse_ingredients(ingredients_text)
    errors += ing_errors
    if not items and not ing_errors:
        errors.append("Add at least one ingredient.")

    if errors:
        return None, errors
    return {"day": day, "meal_type": meal_type, "name": name, "calories": cal, "ingredients": items}, []


# ----------------------------------------------------------------------------
# Business logic: grocery list, summary, search
# ----------------------------------------------------------------------------
def fmt_qty(q):
    return f"{q:g}"


def grocery_list(meals):
    """Aggregate ingredients across the week: same item + same unit are summed."""
    totals = {}
    for m in meals:
        for ing in m["ingredients"]:
            key = (ing["name"].strip().lower(), ing["unit"])
            totals[key] = totals.get(key, 0) + ing["qty"]
    return sorted(((n, u, q) for (n, u), q in totals.items()), key=lambda x: x[0])


def summarize(meals):
    per_day, warnings = {}, []
    for d in DAYS:
        dm = [m for m in meals if m["day"] == d]
        cal = sum(m["calories"] for m in dm)
        have = {m["meal_type"] for m in dm}
        missing = [t for t in MEAL_TYPES[:3] if t not in have]
        if not dm:
            status = "Empty"
            warnings.append(f"{d}: nothing planned yet.")
        else:
            if cal > HIGH_DAY_CAL:
                status = "High"
                warnings.append(f"{d}: {cal} kcal is above the {HIGH_DAY_CAL} kcal daily limit.")
            elif cal < LOW_DAY_CAL:
                status = "Low"
                warnings.append(f"{d}: only {cal} kcal planned (below {LOW_DAY_CAL}).")
            elif missing:
                status = "Incomplete"
            else:
                status = "OK"
            if missing:
                warnings.append(f"{d}: no {', '.join(missing)} planned.")
        per_day[d] = {"cal": cal, "count": len(dm), "status": status, "meals": dm}

    days_planned = sum(1 for v in per_day.values() if v["count"])
    total_cal = sum(v["cal"] for v in per_day.values())
    top = Counter(i["name"].strip().lower() for m in meals for i in m["ingredients"]).most_common(8)
    return {
        "total": len(meals),
        "days_planned": days_planned,
        "total_cal": total_cal,
        "avg": round(total_cal / days_planned) if days_planned else 0,
        "per_day": per_day,
        "warnings": warnings,
        "top_ingredients": top,
        "by_type": Counter(m["meal_type"] for m in meals),
    }


def search_meals(meals, q="", day="", mtype=""):
    q = q.strip().lower()
    out = []
    for m in meals:
        if day and m["day"] != day:
            continue
        if mtype and m["meal_type"] != mtype:
            continue
        if q:
            haystack = m["name"].lower() + " " + " ".join(i["name"].lower() for i in m["ingredients"])
            if q not in haystack:
                continue
        out.append(m)
    return out


# ----------------------------------------------------------------------------
# Charts (Matplotlib -> PNG bytes)
# ----------------------------------------------------------------------------
def render_chart(kind, meals):
    s = summarize(meals)
    fig, ax = plt.subplots(figsize=(6.5, 3.6))
    if not meals:
        ax.text(0.5, 0.5, "No data yet", ha="center", va="center")
        ax.axis("off")
    elif kind == "calories":
        vals = [s["per_day"][d]["cal"] for d in DAYS]
        colors = ["#d9534f" if v > HIGH_DAY_CAL else "#f0ad4e" if 0 < v < LOW_DAY_CAL else "#4c9f70" for v in vals]
        ax.bar([d[:3] for d in DAYS], vals, color=colors)
        ax.axhline(HIGH_DAY_CAL, ls="--", color="#d9534f", lw=1)
        ax.axhline(LOW_DAY_CAL, ls="--", color="#f0ad4e", lw=1)
        ax.set_title("Calories planned per day")
        ax.set_ylabel("kcal")
    elif kind == "types":
        counts = [s["by_type"].get(t, 0) for t in MEAL_TYPES]
        ax.bar(MEAL_TYPES, counts, color="#5b8def")
        ax.set_title("Meals by type")
        ax.set_ylabel("count")
    else:  # ingredients
        top = s["top_ingredients"][::-1]
        ax.barh([n.title() for n, _ in top], [c for _, c in top], color="#9b6bd6")
        ax.set_title("Most-used ingredients (meals using it)")
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110)
    plt.close(fig)
    return buf.getvalue()


# ----------------------------------------------------------------------------
# Export helpers
# ----------------------------------------------------------------------------
def ing_to_cell(ings):
    return ";".join(f"{i['name']}:{fmt_qty(i['qty'])}:{i['unit']}" for i in ings)


def meals_csv(meals):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["day", "meal_type", "name", "calories", "ingredients"])
    for m in sort_meals(meals):
        w.writerow([m["day"], m["meal_type"], m["name"], m["calories"], ing_to_cell(m["ingredients"])])
    return buf.getvalue()


def grocery_csv(meals):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["item", "quantity", "unit"])
    for n, u, q in grocery_list(meals):
        w.writerow([n, fmt_qty(q), u])
    return buf.getvalue()


def summary_markdown(meals):
    s = summarize(meals)
    lines = [
        "# Weekly Meal Plan Summary",
        f"_Generated {datetime.now():%Y-%m-%d %H:%M}_",
        "",
        f"- Meals planned: **{s['total']}**",
        f"- Days planned: **{s['days_planned']}/7**",
        f"- Total calories: **{s['total_cal']} kcal** (avg **{s['avg']} kcal/day**)",
        "",
        "## Per day",
        "| Day | Meals | kcal | Status |",
        "|---|---|---|---|",
    ]
    for d in DAYS:
        v = s["per_day"][d]
        lines.append(f"| {d} | {v['count']} | {v['cal']} | {v['status']} |")
    lines += ["", "## Warnings"] + ([f"- {w}" for w in s["warnings"]] or ["- None"])
    lines += ["", "## Grocery list"]
    lines += [f"- {n.title()}: {fmt_qty(q)} {u}" for n, u, q in grocery_list(meals)]
    return "\n".join(lines) + "\n"


def download(text, filename, media_type):
    return Response(text, media_type=media_type,
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


# ----------------------------------------------------------------------------
# UI helpers (FastHTML)
# ----------------------------------------------------------------------------
app, rt = fast_app()

NAV = [("Planner", "/"), ("Meals", "/meals"), ("Add Meal", "/add"),
       ("Grocery List", "/grocery"), ("Data", "/data")]

STATUS_STYLE = {
    "OK": "color:#2e7d32", "High": "color:#c62828;font-weight:bold",
    "Low": "color:#ef6c00;font-weight:bold", "Incomplete": "color:#ef6c00",
    "Empty": "color:#888",
}


def page(title, *body):
    return (
        Title(f"{title} | Meal Planner Notebook"),
        Main(
            Nav(Ul(Li(Strong("🥗 Meal Planner Notebook"))),
                Ul(*[Li(A(label, href=href)) for label, href in NAV])),
            *body,
            cls="container",
        ),
    )


def flash(msg):
    return Article(msg, style="border-left:6px solid #4c9f70;") if msg else None


def error_box(errors):
    if not errors:
        return None
    return Article(P(Strong("Please fix the following:")), Ul(*[Li(e) for e in errors]),
                   style="border-left:6px solid #d9534f;")


def stat(label, value):
    return Article(H3(str(value), style="margin:0"), P(label, style="margin:0"), style="text-align:center")


def ings_text(ings):
    return ", ".join(f"{i['name']} {fmt_qty(i['qty'])}{i['unit']}" for i in ings)


def meal_form(values=None):
    v = values or {}
    return Form(
        Label("Day", Select(*[Option(d, selected=(d == v.get("day"))) for d in DAYS], name="day")),
        Label("Meal type", Select(*[Option(t, selected=(t == v.get("meal_type"))) for t in MEAL_TYPES], name="meal_type")),
        Label("Meal name", Input(name="name", value=v.get("name", ""), placeholder="e.g. Veg omelette",
                                 required=True, maxlength=60)),
        Label(f"Calories (0-{MAX_CAL} kcal)", Input(name="calories", type="number", value=v.get("calories", ""),
                                                    min=0, max=MAX_CAL, required=True)),
        Label(f"Ingredients - one per line: name, quantity, unit  (units: {', '.join(UNITS)})",
              Textarea(v.get("ingredients", ""), name="ingredients", rows=6,
                       placeholder="eggs, 2, pcs\nonion, 0.5, pcs\ntomato, 1, pcs")),
        Button("Save meal"),
        method="post", action="/add",
    )


# ----------------------------------------------------------------------------
# Routes
# ----------------------------------------------------------------------------
@rt("/")
def get(msg: str = ""):
    meals = load_meals()
    s = summarize(meals)

    rows = []
    for d in DAYS:
        v = s["per_day"][d]
        cells = []
        for t in MEAL_TYPES:
            names = [m["name"] for m in v["meals"] if m["meal_type"] == t]
            cells.append(Td(*([Div(n) for n in names] or [Span("-", style="color:#aaa")])))
        rows.append(Tr(Td(Strong(d)), *cells, Td(v["cal"]),
                       Td(Span(v["status"], style=STATUS_STYLE[v["status"]]))))

    warn = (Article(H4("⚠️ Warnings"), Ul(*[Li(w) for w in s["warnings"]]),
                    style="border-left:6px solid #ef6c00;") if s["warnings"] else
            Article("✅ No warnings - the week looks balanced.", style="border-left:6px solid #4c9f70;"))

    return page(
        "Weekly Planner",
        flash(msg),
        H2("This week's plan"),
        Grid(stat("Meals planned", s["total"]), stat("Days planned", f"{s['days_planned']}/7"),
             stat("Avg kcal / day", s["avg"]), stat("Total kcal", s["total_cal"])),
        Div(Table(Thead(Tr(Th("Day"), *[Th(t) for t in MEAL_TYPES], Th("kcal"), Th("Status"))),
                  Tbody(*rows)), style="overflow-x:auto"),
        warn,
        H2("Charts"),
        Grid(Img(src="/chart/calories", alt="Calories per day"), Img(src="/chart/types", alt="Meals by type")),
        Img(src="/chart/ingredients", alt="Top ingredients", style="max-width:520px"),
    )


@rt("/meals")
def get(q: str = "", day: str = "", mtype: str = "", msg: str = ""):
    meals = sort_meals(search_meals(load_meals(), q, day, mtype))
    search = Form(
        Grid(
            Input(name="q", value=q, placeholder="Search meal or ingredient..."),
            Select(Option("All days", value=""), *[Option(d, selected=(d == day)) for d in DAYS], name="day"),
            Select(Option("All types", value=""), *[Option(t, selected=(t == mtype)) for t in MEAL_TYPES], name="mtype"),
            Button("Search"),
        ),
        method="get", action="/meals",
    )
    rows = [
        Tr(Td(m["day"]), Td(m["meal_type"]), Td(m["name"]), Td(m["calories"]), Td(ings_text(m["ingredients"])),
           Td(Form(Button("Delete", cls="outline secondary", style="padding:2px 10px;margin:0"),
                   method="post", action=f"/delete/{m['id']}")))
        for m in meals
    ]
    return page(
        "Meals",
        flash(msg),
        H2("All meals"),
        search,
        P(f"{len(meals)} result(s)"),
        Div(Table(Thead(Tr(Th("Day"), Th("Type"), Th("Meal"), Th("kcal"), Th("Ingredients"), Th(""))),
                  Tbody(*rows)), style="overflow-x:auto"),
    )


@rt("/add")
def get():
    return page("Add Meal", H2("Add a meal"), meal_form())


@rt("/add")
def post(day: str = "", meal_type: str = "", name: str = "", calories: str = "", ingredients: str = ""):
    clean, errors = validate_meal(day, meal_type, name, calories, ingredients)
    if errors:
        values = {"day": day, "meal_type": meal_type, "name": name, "calories": calories,
                  "ingredients": ingredients}
        return page("Add Meal", H2("Add a meal"), error_box(errors), meal_form(values))
    meals = load_meals()
    clean["id"] = next_id(meals)
    clean["created"] = datetime.now().isoformat(timespec="seconds")
    meals.append(clean)
    save_meals(meals)
    return RedirectResponse(f"/meals?msg=Saved+{clean['name']}", status_code=303)


@rt("/delete/{mid}")
def post(mid: int):
    meals = [m for m in load_meals() if m["id"] != mid]
    save_meals(meals)
    return RedirectResponse("/meals?msg=Meal+deleted", status_code=303)


@rt("/grocery")
def get():
    items = grocery_list(load_meals())
    return page(
        "Grocery List",
        H2("Weekly grocery list"),
        P("Ingredients from every planned meal, combined by item and unit."),
        Table(Thead(Tr(Th("Item"), Th("Quantity"), Th("Unit"))),
              Tbody(*[Tr(Td(n.capitalize()), Td(fmt_qty(q)), Td(u)) for n, u, q in items])),
        A("⬇ Download grocery list (CSV)", href="/export/grocery.csv", role="button"),
    )


@rt("/data")
def get(msg: str = ""):
    return page(
        "Data",
        flash(msg),
        H2("Export"),
        Div(A("Meals CSV", href="/export/meals.csv", role="button"), " ",
            A("Grocery CSV", href="/export/grocery.csv", role="button"), " ",
            A("Summary (Markdown)", href="/export/summary.md", role="button"), " ",
            A("Summary (Text log)", href="/export/summary.txt", role="button")),
        H2("Bulk import (CSV)"),
        P("Columns required: ", Code("day,meal_type,name,calories,ingredients"),
          ". Ingredients are written as ", Code("eggs:2:pcs;onion:1:pcs"),
          ". Tip: export Meals CSV first to see the exact format."),
        Form(Input(type="file", name="file", accept=".csv", required=True), Button("Import"),
             method="post", action="/data/import", enctype="multipart/form-data"),
        H2("Reset"),
        P("Replace everything with the 33 sample entries."),
        Form(Button("Reset to sample data", cls="secondary", onclick="return confirm('Replace all data?')"),
             method="post", action="/data/reset"),
    )


@rt("/data/import")
async def post(file: UploadFile):
    errors, added = [], 0
    try:
        raw = (await file.read()).decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(raw))
        headers = {(h or "").strip().lower() for h in (reader.fieldnames or [])}
        required = {"day", "meal_type", "name", "calories", "ingredients"}
        if not required <= headers:
            errors.append(f"Missing columns: {', '.join(sorted(required - headers))}")
        else:
            meals = load_meals()
            for n, row in enumerate(reader, 2):  # row 1 is the header
                row = {(k or "").strip().lower(): (v or "") for k, v in row.items()}
                ing_text = "\n".join(p.replace(":", ", ") for p in row["ingredients"].split(";"))
                clean, errs = validate_meal(row["day"], row["meal_type"], row["name"], row["calories"], ing_text)
                if errs:
                    errors += [f"Row {n}: {e}" for e in errs]
                    continue
                clean["id"] = next_id(meals)
                clean["created"] = datetime.now().isoformat(timespec="seconds")
                meals.append(clean)
                added += 1
            save_meals(meals)
    except Exception as e:  # unreadable file, bad encoding, etc.
        errors.append(f"Could not read file: {e}")

    return page(
        "Import result",
        H2("Import result"),
        Article(f"✅ Imported {added} meal(s). ❌ {len(errors)} problem(s) found.",
                style="border-left:6px solid #4c9f70;"),
        Article(H4("Row-by-row error log"), Ul(*[Li(e) for e in errors]),
                style="border-left:6px solid #d9534f;") if errors else None,
        A("← Back to Data", href="/data"),
    )


@rt("/data/reset")
def post():
    save_meals(seed_data())
    return RedirectResponse("/?msg=Sample+data+restored", status_code=303)


@rt("/chart/{kind}")
def get(kind: str):
    kind = kind if kind in ("calories", "types", "ingredients") else "calories"
    return Response(render_chart(kind, load_meals()), media_type="image/png",
                    headers={"Cache-Control": "no-store"})


@rt("/export/meals.csv")
def get():
    return download(meals_csv(load_meals()), "meals.csv", "text/csv")


@rt("/export/grocery.csv")
def get():
    return download(grocery_csv(load_meals()), "grocery_list.csv", "text/csv")


@rt("/export/summary.md")
def get():
    return download(summary_markdown(load_meals()), "summary.md", "text/markdown")


@rt("/export/summary.txt")
def get():
    return download(summary_markdown(load_meals()).replace("**", "").replace("#", "").replace("|", " "),
                    "summary_log.txt", "text/plain")


serve()
