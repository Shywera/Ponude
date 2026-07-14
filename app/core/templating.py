"""Zajednička Jinja okolina za sve module + hrvatski format brojeva.

Filteri:
  x|hr(2)        -> 1.234,56   (tisućice točkom, decimale zarezom)
  x|hr(1, true)  -> +16,9      (s predznakom, za delte)
  x|hrg          -> 32,5       (kompaktno, bez tisućica — dimenzije, marže)
"""
import json

from fastapi.templating import Jinja2Templates

from app.modules.auth import security as _sec


def hr(v, dec=2, sign=False):
    if v is None:
        return "—"
    try:
        s = f"{v:+,.{dec}f}" if sign else f"{v:,.{dec}f}"
    except (TypeError, ValueError):
        return str(v)
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def hrg(v):
    if v is None:
        return "—"
    try:
        return f"{v:g}".replace(".", ",")
    except (TypeError, ValueError):
        return str(v)


templates = Jinja2Templates(directory="app/templates")
templates.env.filters["hr"] = hr
templates.env.filters["hrg"] = hrg
templates.env.filters["fromjson"] = json.loads
templates.env.globals["has_perm"] = _sec.has_perm
