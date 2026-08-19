"""
Board registry — maps board names to Granicus view_ids.
"""

BOARDS = {
    "Board of Finance": {
        "view_id": "4",
        "short_name": "BOF",
        "color": "#6366f1",  # indigo
    },
    "Board of Representatives": {
        "view_id": "14",
        "short_name": "BOR",
        "color": "#f59e0b",  # amber
    },
    "Board of Education": {
        "view_id": "3",
        "short_name": "BOE",
        "color": "#10b981",  # emerald
    },
    "Zoning Board": {
        "view_id": "8",
        "short_name": "ZB",
        "color": "#ef4444",  # red
    },
    "Planning Board": {
        "view_id": "20",
        "short_name": "PB",
        "color": "#8b5cf6",  # violet
    },
    "Stamford View": {
        "view_id": "2",
        "short_name": "SV",
        "color": "#0ea5e9",  # sky
    },
    "OPEB": {
        "view_id": "5",
        "short_name": "OPEB",
        "color": "#14b8a6",  # teal
    },
    "Health Commission": {
        "view_id": "6",
        "short_name": "HC",
        "color": "#f43f5e",  # rose
    },
    "Animal Control": {
        "view_id": "7",
        "short_name": "AC",
        "color": "#a3e635",  # lime
    },
    "Parks & Recreation": {
        "view_id": "9",
        "short_name": "PR",
        "color": "#22c55e",  # green
    },
    "Harbor Management": {
        "view_id": "10",
        "short_name": "HM",
        "color": "#06b6d4",  # cyan
    },
    "Traffic Advisory Committee": {
        "view_id": "11",
        "short_name": "TAC",
        "color": "#f97316",  # orange
    },
    "Transit District": {
        "view_id": "12",
        "short_name": "TD",
        "color": "#64748b",  # slate
    },
    "WPCA": {
        "view_id": "15",
        "short_name": "WPCA",
        "color": "#3b82f6",  # blue
    },
    "Environmental Protection Board": {
        "view_id": "17",
        "short_name": "EPB",
        "color": "#84cc16",  # lime-green
    },
    "Historic Preservation": {
        "view_id": "18",
        "short_name": "HP",
        "color": "#d97706",  # amber-dark
    },
    "Zoning Board of Appeals": {
        "view_id": "19",
        "short_name": "ZBA",
        "color": "#dc2626",  # red-dark
    },
    "Camera Review": {
        "view_id": "21",
        "short_name": "CR",
        "color": "#7c3aed",  # purple
    },
    "Fire Commission": {
        "view_id": "22",
        "short_name": "FC",
        "color": "#ea580c",  # orange-dark
    },
    "Police Commission": {
        "view_id": "23",
        "short_name": "PC",
        "color": "#1d4ed8",  # blue-dark
    },
    "Social Services Commission": {
        "view_id": "24",
        "short_name": "SSC",
        "color": "#db2777",  # pink
    },
}


def get_board_by_view_id(view_id: str) -> dict | None:
    """Look up a board by its Granicus view_id."""
    for name, info in BOARDS.items():
        if info["view_id"] == view_id:
            return {"name": name, **info}
    return None


def get_board_by_short_name(short_name: str) -> dict | None:
    """Look up a board by its short name (BOF, BOR, etc.)."""
    for name, info in BOARDS.items():
        if info["short_name"].upper() == short_name.upper():
            return {"name": name, **info}
    return None
