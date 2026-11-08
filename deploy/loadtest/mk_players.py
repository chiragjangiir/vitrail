"""Cree N players de test sur le banc et imprime leurs jetons (un par ligne).

Les jetons sont FORGES SUR PLACE avec le secret JWT de la machine et STOCKES en base :
le WS compare le jeton presente au jeton stocke (revocation, cf. token_identity), donc un
jeton simplement signe mais absent de la base serait refuse.
"""
import asyncio
import sys

from sqlalchemy import select

from app.core.security import create_player_token
from app.db.session import WorkerSessionLocal
from app.models.player import CmsPlayer

PREFIX = "LOADTEST-"
N = int(sys.argv[1]) if len(sys.argv) > 1 else 400
ID_ORG = 1


async def main() -> None:
    async with WorkerSessionLocal() as db:
        existing = (await db.execute(
            select(CmsPlayer).where(CmsPlayer.player_name.like(PREFIX + "%"))
        )).scalars().all()
        if existing:
            print(f"ERREUR: {len(existing)} players {PREFIX}* existent deja", file=sys.stderr)
            sys.exit(2)

        players = []
        for i in range(1, N + 1):
            p = CmsPlayer(
                id_org=ID_ORG,
                player_name=f"{PREFIX}{i:04d}",
                player_os="linux",
                status="offline",
            )
            db.add(p)
            players.append(p)
        await db.flush()

        tokens = []
        for p in players:
            tok, exp = create_player_token(p.id_player)
            p.player_token = tok
            p.token_expires_at = exp
            tokens.append(tok)
        await db.commit()

    for t in tokens:
        print(t)
    print(f"CREATED {len(tokens)}", file=sys.stderr)


asyncio.run(main())
