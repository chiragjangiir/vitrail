"""Métadonnées de build — version de la release en cours d'exécution.

Endpoint PUBLIC (non authentifié) volontairement : la version n'est pas un
secret (elle est déjà exposée par /health), et l'afficher avant connexion aide
le support autant que l'exploitant. Ne renvoie QUE la version — rien d'autre.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import (
    get_current_user, get_db_worker, require_org_admin, require_server_operator,
)
from app.models.user import CmsUser
from app.services import rbac
from app.services.update_check import check_for_update

router = APIRouter(prefix="/meta", tags=["system"])


@router.get("")
async def get_meta() -> dict:
    return {"version": settings.SIGNFLOW_VERSION}


@router.get("/update")
async def get_update_status(
    current_user: Annotated[CmsUser, Depends(require_org_admin)],
) -> dict:
    """Une MAJ serveur plus récente est-elle publiée ?

    Réservé à l'org-admin (= l'exploitant sur une install self-hosted). Best-effort
    et transparent : jamais d'erreur si le manifeste est injoignable. La cloche
    reste muette sur un build source ("dev") ou une prod dont l'interrupteur est
    coupé (SIGNFLOW_UPDATE_BELL=false).
    """
    locale = (current_user.locale or "en")[:2]
    return await check_for_update(settings.SIGNFLOW_VERSION, locale)


@router.get("/operator")
async def get_operator_status(
    current_user: Annotated[CmsUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db_worker)],
) -> dict:
    """L'utilisateur courant exploite-t-il ce serveur ? (affichage des gestes d'exploitant)"""
    return {"is_operator": await rbac.user_is_server_operator(db, current_user)}


@router.get("/server")
async def get_server_status(
    current_user: Annotated[CmsUser, Depends(require_server_operator)],
    db: Annotated[AsyncSession, Depends(get_db_worker)],
) -> dict:
    """Signalétique du SERVEUR : capacité d'encodage, débits constatés, file en cours.

    Gate = `require_server_operator` : super-admin, ou org-admin d'un serveur sans
    super-admin. Sur un serveur mutualisé, un org-admin d'une organisation hébergée reçoit
    403 et ne voit donc pas la file d'encodage des autres organisations.

    Le backend n'ayant ni ffmpeg ni GPU, les capacités viennent du WORKER (Redis, TTL) :
    aucun worker qui répond = on le dit, au lieu d'afficher les capacités d'une machine
    éteinte.
    """
    from sqlalchemy import func, select

    from app.models.media import CmsMedia
    from app.services import encode_progress, worker_status

    workers = await worker_status.read_all()

    # File d'encodage — TOUTES organisations confondues : c'est une ressource de la
    # MACHINE, et l'exploitant du serveur est celui qui la gère.
    busy = (await db.execute(
        select(CmsMedia.id_media, CmsMedia.media_name, CmsMedia.transcode_status,
               CmsMedia.id_org, CmsMedia.media_metadata)
        .where(CmsMedia.is_deleted.is_(False),
               CmsMedia.transcode_status.in_(("pending", "processing", "awaiting_decision")))
        .order_by(CmsMedia.updated_at.desc())
        .limit(50)
    )).all()
    progress = await encode_progress.read_many(
        [r.id_media for r in busy if r.transcode_status == "processing"]
    )
    queue = [{
        "id_media": r.id_media,
        "media_name": r.media_name,
        "id_org": r.id_org,
        "transcode_status": r.transcode_status,
        "encode_progress": progress.get(r.id_media),
        "encode_decision": (r.media_metadata or {}).get("encode_decision")
        if r.transcode_status == "awaiting_decision" else None,
    } for r in busy]

    # Débits RÉELLEMENT constatés, relevés à chaque encodage (aucune table dédiée : la
    # mesure vit sur le média qu'elle décrit). Agrégés par encodeur — c'est la réponse
    # honnête à « ce serveur encode-t-il vite ? ».
    rows = (await db.execute(
        select(CmsMedia.media_metadata)
        .where(CmsMedia.is_deleted.is_(False),
               CmsMedia.media_metadata["encode"].isnot(None))
        .order_by(CmsMedia.updated_at.desc())
        .limit(200)
    )).scalars().all()
    by_encoder: dict[str, list[float]] = {}
    samples: list[dict] = []
    for meta in rows:
        enc = (meta or {}).get("encode") or {}
        name, speed = enc.get("encoder"), enc.get("speed")
        if not name or not speed:
            continue
        by_encoder.setdefault(name, []).append(float(speed))
        if len(samples) < 10:
            samples.append(enc)
    throughput = [
        {"encoder": name, "samples": len(v), "avg_speed": round(sum(v) / len(v), 3)}
        for name, v in sorted(by_encoder.items())
    ]

    total_bytes = (await db.execute(
        select(func.coalesce(func.sum(CmsMedia.file_size_bytes), 0))
        .where(CmsMedia.is_deleted.is_(False))
    )).scalar() or 0
    media_count = (await db.execute(
        select(func.count()).select_from(CmsMedia).where(CmsMedia.is_deleted.is_(False))
    )).scalar() or 0

    return {
        "version": settings.SIGNFLOW_VERSION,
        "workers": workers,
        "queue": queue,
        "throughput": throughput,
        "recent_encodes": samples,
        "media": {"count": media_count, "total_bytes": int(total_bytes)},
        # Les bandes affichées à l'écran viennent du SERVEUR : dupliquer ces valeurs
        # côté front garantirait qu'elles divergent un jour de ce que le worker applique.
        "encode_bands": {
            "auto_below_s": media_worker_bands()[0],
            "refuse_above_s": media_worker_bands()[1],
        },
    }


def media_worker_bands() -> tuple[int, int]:
    """Bandes de décision telles que le worker les applique (source unique)."""
    from app.workers.media_worker import ENCODE_BAND_AUTO_S, ENCODE_BAND_REFUSE_S

    return ENCODE_BAND_AUTO_S, ENCODE_BAND_REFUSE_S
