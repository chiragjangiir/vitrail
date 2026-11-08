"""Generateur de rafale de reconnexion.

Protocole (identique au 02/08 et au 07/08) : N connexions WebSocket player lancees
SIMULTANEMENT, mesure du delai jusqu'au premier message `player:sync`.

Nouveaute du 08/08 : le generateur peut etre DECOUPE en plusieurs processus. La barriere
n'est plus interne (asyncio.Barrier) mais une DATE ABSOLUE passee en argument : tous les
processus, sur la meme machine donc la meme horloge, partent au meme instant. Cela permet
de rejouer la meme charge serveur avec 1 processus x 400 ou 2 processus x 200.

Sortie : un JSON sur stdout {tag, n, ok, err, t0, first_open, last_sync, lat:[...]}.
Les latences sont mesurees depuis T0 (la barriere), pas depuis l'ouverture individuelle :
c'est le delai que subirait un ecran dans une rafale reelle.
"""
import argparse
import asyncio
import json
import sys
import time

import websockets

p = argparse.ArgumentParser()
p.add_argument("--tokens", required=True)
p.add_argument("--offset", type=int, default=0)
p.add_argument("--count", type=int, required=True)
p.add_argument("--url", required=True)  # ex: ws://127.0.0.1:8080/api/v1/ws/player
p.add_argument("--t0", type=float, required=True)  # epoch absolu du depart
p.add_argument("--tag", required=True)
p.add_argument("--hold", type=float, default=5.0)  # duree de maintien apres le dernier sync
args = p.parse_args()

with open(args.tokens) as fh:
    tokens = [ln.strip() for ln in fh if ln.strip()]
tokens = tokens[args.offset:args.offset + args.count]
assert len(tokens) == args.count, f"{len(tokens)} jetons pour {args.count} demandes"

lat: list[float] = []
errs: list[str] = []
opens: list[float] = []
syncs: list[float] = []
done = asyncio.Event()


async def one(token: str) -> None:
    uri = f"{args.url}?token={token}"
    try:
        opens.append(time.time())
        async with websockets.connect(uri, open_timeout=120, close_timeout=5,
                                      max_size=None, ping_interval=None) as ws:
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=120)
                msg = json.loads(raw)
                if msg.get("type") == "player:sync":
                    now = time.time()
                    syncs.append(now)
                    lat.append(now - args.t0)
                    break
            # On MAINTIENT la connexion ouverte : la rafale n'est fidele que si les 400
            # connexions coexistent reellement pendant la montee en charge.
            await done.wait()
    except Exception as exc:  # noqa: BLE001
        errs.append(f"{type(exc).__name__}: {exc}")


async def main() -> None:
    wait = args.t0 - time.time()
    if wait < 0:
        print(json.dumps({"tag": args.tag, "fatal": f"T0 deja passe de {-wait:.2f}s"}))
        sys.exit(3)
    await asyncio.sleep(wait)
    tasks = [asyncio.create_task(one(t)) for t in tokens]
    # Attente de la fin des syncs (ou des erreurs), puis maintien, puis liberation.
    deadline = time.time() + 180
    while len(lat) + len(errs) < len(tokens) and time.time() < deadline:
        await asyncio.sleep(0.05)
    await asyncio.sleep(args.hold)
    done.set()
    await asyncio.gather(*tasks, return_exceptions=True)
    print(json.dumps({
        "tag": args.tag, "n": len(tokens), "ok": len(lat), "err": len(errs),
        "t0": args.t0,
        "first_open": min(opens) if opens else None,
        "last_sync": max(syncs) if syncs else None,
        "errs": errs[:5],
        "lat": lat,
    }))


asyncio.run(main())
