"""every tab the dashboard knows about.

key   -> short name the code uses (e.g. pending_tab = "dry_creek")
label -> what shows in the sidebar
module -> file in this folder with a render(ctx) function

order here = order in the sidebar.
adding a tab = drop a new file in here with `def render(ctx):` and add a line below.
a tab's module only gets imported when someone opens it.
"""
import importlib

TABS = {
    "overview":         ("Overview", "overview"),
    "dcc_mission":      ("Dry Creek Conservancy (DCC) & Mission", "dcc_mission"),
    "dry_creek":        ("Dry creek", "creek_detail"),
    "miners_ravine":    ("Miners Ravine", "creek_detail"),   # same page as dry creek, just the other site
    "monitoring_sites": ("Monitoring Sites", "monitoring_sites"),
    "comparative":      ("Comparative analysis", "comparative"),
    "correlation":      ("Correlation analysis", "correlation"),
    "downloads":        ("PDF & Data Download", "downloads"),
    "edna":             ("eDNA results", "edna"),
    "simulation":       ("Simulation", "simulation"),
    "upload":           ("Upload Data", "upload"),
    "historical":       ("Historical Analysis", "historical"),
}


def label(key):
    return TABS[key][0]


def render(key, ctx):
    mod = importlib.import_module(f"dcc_dashboard.tabs.{TABS[key][1]}")
    mod.render(ctx)

