"""Agrege les sorties JSON du generateur et rend le verdict d'un run.

Les percentiles sont calcules sur l'UNION des latences : 2 processus x 200 doivent etre
compares a 1 processus x 400 sur le meme echantillon de 400, sinon on comparerait deux
populations differentes.

Temoin d'ENTRELACEMENT : deux generateurs qui se relaieraient au lieu de se superposer
donneraient une charge serveur deux fois plus faible et un verdict faux. On exige donc que
les fenetres [first_open, last_sync] des processus se CHEVAUCHENT.
"""
import json
import statistics
import sys

run, mode = sys.argv[1], sys.argv[2]
parts = []
for path in sys.argv[3:]:
    with open(path) as fh:
        parts.append(json.load(fh))

lat = sorted(x for p in parts for x in p["lat"])
n = sum(p["n"] for p in parts)
ok = sum(p["ok"] for p in parts)
err = sum(p["err"] for p in parts)


def pct(vals, q):
    if not vals:
        return float("nan")
    k = max(0, min(len(vals) - 1, int(round(q * (len(vals) - 1)))))
    return vals[k]


overlap = "n/a (1 processus)"
if len(parts) > 1:
    a, b = parts[0], parts[1]
    if a["first_open"] and b["first_open"] and a["last_sync"] and b["last_sync"]:
        start = max(a["first_open"], b["first_open"])
        end = min(a["last_sync"], b["last_sync"])
        span = min(a["last_sync"] - a["first_open"], b["last_sync"] - b["first_open"])
        overlap = (f"{end - start:.2f}s de chevauchement sur {span:.2f}s "
                   f"=> {'OK' if end - start > 0.8 * span else 'INSUFFISANT'}")

print(json.dumps({
    "run": run, "mode": mode, "n": n, "ok": ok, "err": err,
    "p50": round(pct(lat, 0.50), 3), "p95": round(pct(lat, 0.95), 3),
    "max": round(max(lat), 3) if lat else None,
    "min": round(min(lat), 3) if lat else None,
    "moyenne": round(statistics.fmean(lat), 3) if lat else None,
    "chevauchement": overlap,
    "erreurs": [e for p in parts for e in p["errs"]][:3],
}))
