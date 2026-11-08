"""Plafonds de dépense BYOK (P3.2, migr 0126).

Le CMS enregistrait le coût de chaque job mais **rien ne bloquait**. En BYOK c'est l'argent
du CLIENT : une boucle ou un import massif se voit sur SA facture, pas sur la nôtre.

Ce que ces tests figent :
  1. le refus arrive **AVANT** l'appel fournisseur — seule position où il ne coûte rien ;
  2. 🔑 **RÉSERVATION, PAS CONSTAT** : deux générations lancées ensemble ne peuvent pas
     passer toutes les deux sous un plafond qui n'en tient qu'une. C'est le point non
     évident, et le seul que l'implémentation naïve rate ;
  3. une réservation **relâchée** cesse de compter, une réservation **soldée** compte au
     montant réel ;
  4. le refus PORTE de quoi distinguer un plafond d'une panne (scope/période/plafond/
     dépensé/restant) — sinon l'écran affiche « erreur » et on cherche le réseau ;
  5. sans plafond, rien ne bloque **et le registre se remplit quand même** (il servira le
     jour où l'on veut poser un plafond, et l'écran de dépense s'en sert déjà) ;
  6. un plafond par UTILISATEUR arrête la boucle d'une personne sans bloquer l'organisation.
"""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.generation import CmsAiSpend
from app.models.organization import CmsOrganization, CmsOrgAuthSettings
from app.models.user import CmsUser
from app.services import spend
from app.core.security import hash_password


@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    o = CmsOrganization(org_name="SpendOrg", org_slug=f"sp-{uuid.uuid4().hex[:8]}")
    db_session.add(o)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db_session.commit()
    await db_session.refresh(o)
    return o


@pytest_asyncio.fixture
async def user(db_session: AsyncSession, org: CmsOrganization) -> CmsUser:
    u = CmsUser(id_org=org.id_org, email=f"s-{uuid.uuid4().hex[:8]}@t.com",
                password_hash=hash_password("Password1!"), is_active=True)
    db_session.add(u)
    await db_session.commit()
    await db_session.refresh(u)
    return u


async def _set_caps(db: AsyncSession, org: CmsOrganization, *, org_cap=None,
                    user_cap=None, period="month") -> None:
    org.ai_spend_cap_usd = org_cap
    org.ai_user_spend_cap_usd = user_cap
    org.ai_spend_cap_period = period
    await db.commit()


# ── Périodes : fonction pure ───────────────────────────────────────────────────

def test_period_start_is_calendar_and_utc() -> None:
    """Jour / semaine ISO / mois, calendaires, en UTC.

    ⚠️ Le cas qui compte est le fuseau : un instant tard le soir en Europe appartient DÉJÀ
    au lendemain UTC. Si on calculait en heure locale, le plafond « du jour » changerait de
    borne selon l'endroit d'où l'on regarde.
    """
    # Mercredi 2026-08-12, 23:30 en UTC+2 → 21:30 UTC, encore le 12 UTC.
    t = datetime(2026, 8, 12, 23, 30, tzinfo=timezone(timedelta(hours=2)))
    assert spend.period_start("day", t) == datetime(2026, 8, 12, tzinfo=timezone.utc)
    assert spend.period_start("week", t) == datetime(2026, 8, 10, tzinfo=timezone.utc)  # lundi
    assert spend.period_start("month", t) == datetime(2026, 8, 1, tzinfo=timezone.utc)
    # Le même instant, mais 01:30 en UTC+2 → 23:30 UTC la VEILLE.
    t2 = datetime(2026, 8, 13, 1, 30, tzinfo=timezone(timedelta(hours=2)))
    assert spend.period_start("day", t2) == datetime(2026, 8, 12, tzinfo=timezone.utc)


# ── Le refus arrive avant l'appel ──────────────────────────────────────────────

async def test_refuses_before_the_provider_call(
    db_session: AsyncSession, org: CmsOrganization, user: CmsUser
) -> None:
    await _set_caps(db_session, org, org_cap=1.00)
    await spend.reserve(db_session, id_org=org.id_org, id_user=user.id_user,
                        provider="fal", kind="image", model="m", estimated_usd=0.80)
    await db_session.commit()

    with pytest.raises(spend.SpendCapExceeded) as e:
        await spend.reserve(db_session, id_org=org.id_org, id_user=user.id_user,
                            provider="fal", kind="image", model="m", estimated_usd=0.50)
    d = e.value.as_detail()
    assert d["code"] == "spend_cap_exceeded"
    assert d["scope"] == "org"
    assert d["cap_usd"] == 1.00
    assert d["spent_usd"] == 0.80
    # Ce qui distingue un plafond d'une panne : l'écran peut écrire « il reste 0,20 $ ».
    assert d["remaining_usd"] == 0.20


async def test_a_release_stops_counting(
    db_session: AsyncSession, org: CmsOrganization, user: CmsUser
) -> None:
    """Une réservation relâchée (l'appel n'a pas eu lieu) libère le plafond.

    Sans ça, une réservation abandonnée bloquerait l'organisation alors qu'aucune facture
    n'existe.
    """
    await _set_caps(db_session, org, org_cap=1.00)
    sid = await spend.reserve(db_session, id_org=org.id_org, id_user=user.id_user,
                              provider="fal", kind="image", model="m", estimated_usd=0.90)
    await db_session.commit()
    await spend.release(db_session, sid)
    await db_session.commit()

    # Plus rien ne retient : la génération suivante passe.
    await spend.reserve(db_session, id_org=org.id_org, id_user=user.id_user,
                        provider="fal", kind="image", model="m", estimated_usd=0.90)
    await db_session.commit()


async def test_settling_replaces_the_estimate_with_the_real_amount(
    db_session: AsyncSession, org: CmsOrganization, user: CmsUser
) -> None:
    """Le plafond suit la FACTURE, pas l'estimation, dès que le montant réel est connu."""
    await _set_caps(db_session, org, org_cap=1.00)
    sid = await spend.reserve(db_session, id_org=org.id_org, id_user=user.id_user,
                              provider="fal", kind="image", model="m", estimated_usd=0.90)
    await db_session.commit()
    await spend.settle(db_session, sid, 0.10)   # l'appel a coûté bien moins que prévu
    await db_session.commit()

    since = spend.period_start("month", datetime.now(timezone.utc))
    assert await spend.spent_since(db_session, org.id_org, since) == pytest.approx(0.10)
    # Et donc la génération suivante, qui aurait été refusée sur l'estimation, passe.
    await spend.reserve(db_session, id_org=org.id_org, id_user=user.id_user,
                        provider="fal", kind="image", model="m", estimated_usd=0.80)
    await db_session.commit()


# ── LE point non évident : la simultanéité ─────────────────────────────────────

async def test_two_simultaneous_generations_cannot_both_pass(
    engine, monkeypatch, db_session: AsyncSession, org: CmsOrganization, user: CmsUser
) -> None:
    """🔑 Deux générations lancées ENSEMBLE sous un plafond qui n'en tient qu'une.

    C'est exactement ce que rate l'implémentation naïve : les deux lisent la somme AVANT que
    l'une ou l'autre n'ait écrit, se trouvent toutes deux sous le plafond, et le dépassent
    ensemble. Le verrou consultatif de transaction sérialise contrôle + écriture PAR
    ORGANISATION.

    ⚠️ L'ENTRELACEMENT EST FORCÉ, il n'est pas espéré. Mon premier jet se contentait d'un
    `asyncio.gather` : mesuré par mutation, **il restait vert quand on RETIRAIT le verrou**
    — les deux coroutines ne s'entrelaçaient pas au moment critique, et le test ne prouvait
    donc rien de ce qu'il annonçait. On intercale ici une barrière juste APRÈS la lecture de
    la somme :
      · sans verrou → les deux atteignent la barrière, lisent 0, et passent ⇒ test ROUGE ;
      · avec verrou → le second n'atteint jamais la lecture avant le commit du premier ; il
        attend l'expiration de la barrière, puis voit la ligne déjà écrite ⇒ test VERT.
    Une barrière SANS expiration bloquerait l'implémentation correcte : c'est le délai qui
    permet au test de distinguer les deux cas au lieu de se figer.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker

    # ⚠️ Les deux sessions concurrentes se construisent sur l'engine DE TEST. Mon premier
    # jet importait `WorkerSessionLocal`, qui pointe sur la base APPLICATIVE : l'organisation
    # n'y existait pas, aucun plafond n'était lu, et le test échouait en accusant un code
    # parfaitement juste. Un test qui n'interroge pas la même base ne prouve rien.
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    await _set_caps(db_session, org, org_cap=1.00)

    arrived: list[int] = []
    both = asyncio.Event()
    original = spend.spent_since

    async def barriered(*args, **kwargs):
        value = await original(*args, **kwargs)
        arrived.append(1)
        if len(arrived) >= 2:
            both.set()
        try:                                  # laisse l'autre arriver, s'il le peut
            await asyncio.wait_for(both.wait(), timeout=1.0)
        except asyncio.TimeoutError:
            pass
        return value

    monkeypatch.setattr(spend, "spent_since", barriered)

    async def attempt() -> str:
        async with factory() as db:
            try:
                await spend.reserve(db, id_org=org.id_org, id_user=user.id_user,
                                    provider="fal", kind="image", model="m",
                                    estimated_usd=0.80)
                await db.commit()
                return "ok"
            except spend.SpendCapExceeded:
                await db.rollback()
                return "refused"

    results = await asyncio.gather(attempt(), attempt())
    assert sorted(results) == ["ok", "refused"], (
        f"les deux ont passé le plafond : {results} — la réservation ne sérialise pas")

    # Et la base ne porte qu'UNE réservation : le refus n'a rien écrit.
    n = (await db_session.execute(
        select(func.count()).select_from(CmsAiSpend)
        .where(CmsAiSpend.id_org == org.id_org, CmsAiSpend.status != "released")
    )).scalar()
    assert n == 1


# ── Plafond par utilisateur ────────────────────────────────────────────────────

async def test_user_cap_stops_one_person_without_blocking_the_org(
    db_session: AsyncSession, org: CmsOrganization, user: CmsUser
) -> None:
    other = CmsUser(id_org=org.id_org, email=f"o-{uuid.uuid4().hex[:8]}@t.com",
                    password_hash=hash_password("Password1!"), is_active=True)
    db_session.add(other)
    await db_session.commit()
    await db_session.refresh(other)

    await _set_caps(db_session, org, org_cap=None, user_cap=1.00)
    await spend.reserve(db_session, id_org=org.id_org, id_user=user.id_user,
                        provider="fal", kind="image", model="m", estimated_usd=0.90)
    await db_session.commit()

    with pytest.raises(spend.SpendCapExceeded) as e:
        await spend.reserve(db_session, id_org=org.id_org, id_user=user.id_user,
                            provider="fal", kind="image", model="m", estimated_usd=0.50)
    assert e.value.as_detail()["scope"] == "user"

    # L'AUTRE compte n'est pas bloqué : c'est bien la boucle d'UNE personne qu'on arrête.
    await spend.reserve(db_session, id_org=org.id_org, id_user=other.id_user,
                        provider="fal", kind="image", model="m", estimated_usd=0.90)
    await db_session.commit()


# ── Sans plafond ───────────────────────────────────────────────────────────────

async def test_without_a_cap_nothing_blocks_but_the_ledger_still_fills(
    db_session: AsyncSession, org: CmsOrganization, user: CmsUser
) -> None:
    """Aucune organisation ne change de comportement au déploiement (NULL = pas de plafond).

    Mais le registre se remplit quand même : un registre qui ne se remplirait qu'en présence
    d'un plafond serait vide le jour où l'on veut en poser un — et l'écran de dépense
    n'aurait rien à montrer.
    """
    for _ in range(3):
        await spend.reserve(db_session, id_org=org.id_org, id_user=user.id_user,
                            provider="fal", kind="image", model="m", estimated_usd=99.0)
    await db_session.commit()

    since = spend.period_start("month", datetime.now(timezone.utc))
    assert await spend.spent_since(db_session, org.id_org, since) == pytest.approx(297.0)
    u = await spend.usage(db_session, org.id_org, id_user=user.id_user)
    assert u["org_cap_usd"] is None
    assert u["org_spent_usd"] == pytest.approx(297.0)


async def test_zero_means_no_cap(
    db_session: AsyncSession, org: CmsOrganization, user: CmsUser
) -> None:
    """0 = aucun plafond — c'est la seule façon d'en RETIRER un, `update_org` filtrant les
    `None` (`exclude_none=True`). Même convention que `ai_quota_tokens`."""
    await _set_caps(db_session, org, org_cap=0)
    await spend.reserve(db_session, id_org=org.id_org, id_user=user.id_user,
                        provider="fal", kind="image", model="m", estimated_usd=1000.0)
    await db_session.commit()
    caps = await spend.load_caps(db_session, org.id_org)
    assert caps.org_cap_usd is None


async def test_spend_outside_the_period_does_not_count(
    db_session: AsyncSession, org: CmsOrganization, user: CmsUser
) -> None:
    """Le plafond est CALENDAIRE : la dépense du mois dernier ne pèse pas sur celui-ci."""
    await _set_caps(db_session, org, org_cap=1.00, period="day")
    old = CmsAiSpend(id_org=org.id_org, id_user=user.id_user, provider="fal", kind="image",
                     estimated_usd=50.0, status="settled", actual_usd=50.0,
                     created_at=datetime.now(timezone.utc) - timedelta(days=3))
    db_session.add(old)
    await db_session.commit()

    # 50 $ dépensés il y a 3 jours, plafond QUOTIDIEN de 1 $ → la génération du jour passe.
    await spend.reserve(db_session, id_org=org.id_org, id_user=user.id_user,
                        provider="fal", kind="image", model="m", estimated_usd=0.50)
    await db_session.commit()
