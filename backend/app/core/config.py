from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.pooling import DEFAULT_CONNECTION_BUDGET, derive_pool_sizes


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ── Version applicative ──────────────────────────────────────────────────
    # Tag de release servi par le registre (SIGNFLOW_VERSION du .env client, ex.
    # "1.0.5"). Exposé par /health et /api/v1/meta, affiché en pied de sidebar :
    # un intégrateur/client sait à l'œil quelle version tourne sur son serveur.
    # "dev" par défaut = build depuis les sources (banc de dev, prod historique).
    SIGNFLOW_VERSION: str = "dev"

    # ── Cloche « MAJ serveur disponible » (self-hosted) ──────────────────────
    # Un serveur épinglé sur une release (SIGNFLOW_VERSION="1.0.x") sonde un
    # MANIFESTE public pour savoir si une version plus récente est publiée, et
    # affiche une cloche à l'org-admin (= l'exploitant sur une install client).
    # On lit un manifeste, PAS les tags du registre : lui seul porte la version
    # RECOMMANDÉE (on proscrit une release cassée), les notes et un flag sécurité,
    # et il se sonde sans identifiants registre. Un build source ("dev") n'a pas
    # de version comparable ⇒ la cloche reste muette (cas de la prod SaaS).
    SIGNFLOW_UPDATE_MANIFEST_URL: str = (
        "https://raw.githubusercontent.com/edkahall/signflow-install/main/versions.json"
    )
    # Interrupteur : true = self-hosted (défaut, le client/intégrateur exploite son
    # serveur). Mettre à false sur une prod multi-tenant qu'on exploite nous-mêmes
    # pour ne pas notifier les org-admins locataires d'une MAJ qu'ils ne font pas.
    SIGNFLOW_UPDATE_BELL: bool = True

    # ── Base de données ──────────────────────────────────────────────────────
    DATABASE_URL: str = "postgresql+asyncpg://signflow:signflow@localhost:5432/signflow"
    # URL du rôle BYPASSRLS — utilisé par auth et workers Celery (§II.1)
    # Si vide, dérivée automatiquement depuis DATABASE_URL (dev local)
    DATABASE_WORKER_URL: str = ""
    # URL du rôle applicatif signflow_app (non-superuser, SOUMIS à la RLS — §II.1).
    # Si vide, dérivée depuis DATABASE_URL (dev local). ⚠️ En prod : surcharger si le
    # rôle signflow_app n'utilise pas le mot de passe par défaut signflow_app_secret.
    DATABASE_APP_URL: str = ""

    # ── Dimensionnement des pools de connexions (P3.12) ──────────────────────
    # Un processus backend ouvre DEUX pools : l'applicatif (soumis RLS) et celui du rôle
    # BYPASSRLS. Sa consommation MAXIMALE est donc la somme des quatre valeurs ci-dessous
    # — un point que le cadrage de P3.12 avait sous-estimé en ne comptant que le premier.
    #
    # ⚠️ Ne pas lire ces quatre valeurs directement : passer par `effective_pool_sizes`.
    # Laissées à leur défaut, elles sont RECALCULÉES à partir du nombre de processus et du
    # budget (cf. app/core/pooling.py) — sinon multiplier les processus multiplierait les
    # connexions et ferait échouer le démarrage. Les renseigner explicitement reprend la
    # main sur ce calcul.
    CMS_DB_POOL_SIZE: int = 10
    CMS_DB_MAX_OVERFLOW: int = 20
    CMS_DB_WORKER_POOL_SIZE: int = 5
    CMS_DB_WORKER_MAX_OVERFLOW: int = 10

    # Nombre de processus uvicorn. `WEB_CONCURRENCY` est le nom conventionnel (uvicorn,
    # gunicorn, Heroku) : le garder évite d'inventer un réglage de plus. 1 = mono-processus,
    # qui SÉRIALISE les résolutions de programme lors d'une rafale de reconnexions.
    # ⚠️ Le défaut « 1 » ne décrit PAS ce que voit un serveur installé : l'entrypoint de
    # l'image (backend/docker-entrypoint.sh) calcule la valeur à partir des cœurs de la
    # machine avant de lancer uvicorn. Ce défaut vaut pour les tests et pour un backend
    # lancé à la main.
    WEB_CONCURRENCY: int = 1

    @field_validator("WEB_CONCURRENCY", mode="before")
    @classmethod
    def _web_concurrency_auto(cls, v):
        """« auto » (ou vide) vaut 1 ICI, sans jamais faire échouer la configuration.

        🔴 Sans cette tolérance, `docker compose exec backend …` PLANTE : `exec` ne passe
        pas par l'entrypoint de l'image, donc la valeur brute « auto » posée par le compose
        atteint pydantic telle quelle. Or c'est exactement ainsi qu'on lance
        `alembic upgrade head` à chaque déploiement, et les scripts de maintenance.
        Trouvé en exécutant, jamais visible en relecture.

        Le serveur, lui, reçoit toujours un entier : l'entrypoint calcule la valeur avant
        de lancer uvicorn. Le repli à 1 ne concerne donc que les processus ponctuels, pour
        lesquels un seul jeu de pools est de toute façon ce qu'on veut.
        """
        if isinstance(v, str) and not v.strip().isdigit():
            return 1
        return v

    # Connexions PostgreSQL que l'ENSEMBLE des processus backend a le droit de consommer.
    # Volontairement inférieur à `max_connections` (100 par défaut) : les quatre processus
    # Celery, les migrations et la maintenance tirent sur la même réserve, et une base qui
    # refuse une connexion ne dégrade pas — elle casse.
    # Définition UNIQUE dans `core/pooling.py` : l'entrypoint de l'image la lit au même
    # endroit pour plafonner le nombre de processus. Deux copies finiraient par diverger,
    # et l'écart ne se verrait qu'au démarrage d'un serveur client.
    CMS_DB_CONNECTION_BUDGET: int = DEFAULT_CONNECTION_BUDGET

    # ── Redis ────────────────────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"

    # ── Auth JWT ─────────────────────────────────────────────────────────────
    CMS_JWT_SECRET: str = "changeme"
    CMS_JWT_ALGORITHM: str = "HS256"
    CMS_JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    CMS_JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    # Jeton d'enrôlement 2FA : le temps de scanner un QR code et de saisir un code, pas plus.
    # Il n'ouvre que /auth/totp/setup et /auth/totp/verify (cf. get_user_for_totp_enrolment).
    CMS_JWT_ENROLMENT_TOKEN_EXPIRE_MINUTES: int = 10

    # ── Tokens machine des players (politique 2026-06-26 — « Option B ») ────────
    # Le token player expire (durée ci-dessous) mais l'expiration ne coupe JAMAIS un
    # écran : elle déclenche une rotation. Auto-refresh proactif des players online
    # (check_player_health) + grâce-à-la-reconnexion sur le WS pour les players qui
    # étaient offline pendant leur fenêtre de refresh. Manuel = uniquement révocation
    # délibérée par un admin. cf. CLAUDE.md / [[project-player-token-policy]].
    CMS_PLAYER_TOKEN_EXPIRE_DAYS: int = 60
    # Players online : on fait tourner le token quand il reste ≤ N jours avant expiration.
    CMS_PLAYER_TOKEN_REFRESH_DAYS: int = 20
    # Fenêtre pendant laquelle l'ANCIEN token (player_token_prev) reste accepté après une
    # rotation — couvre un push token:refresh raté / un player offline au moment de la rotation.
    CMS_PLAYER_TOKEN_GRACE_DAYS: int = 14

    # ── 2FA globale ──────────────────────────────────────────────────────────
    # disabled | optional | required — politique plateforme (§2.1.1)
    CMS_2FA_GLOBAL_POLICY: str = "optional"

    # ── CORS ─────────────────────────────────────────────────────────────────
    CORS_ORIGINS: List[str] = ["http://localhost:3000"]

    # ── Doc API interactive (/api/docs, /api/redoc, /api/openapi.json) ────────
    # Expose la cartographie complète de l'API. À METTRE À false EN PROD
    # (CMS_DOCS_ENABLED=false dans le .env) — gardée à true pour le dev.
    CMS_DOCS_ENABLED: bool = True

    # ── Rate-limit global API (audit sécurité 2026-06-25) ────────────────────
    # Garde-fou anti-flood par IP sur TOUTE l'API (le login a son propre compteur
    # d'échecs plus strict). Fenêtre fixe en Redis ; fail-open si Redis indisponible
    # (on ne bloque pas le trafic légitime si l'infra de comptage tombe).
    CMS_RATE_LIMIT_ENABLED: bool = True
    CMS_RATE_LIMIT_PER_MINUTE: int = 600

    # ── Store Control Panel LAN (§19.3) ──────────────────────────────────────
    # Port du serveur HTTP embarqué du player ; sert à construire l'URL LAN du QR code.
    LOCAL_CONTROL_PORT: int = 8765

    # ── Stockage MinIO / S3 ──────────────────────────────────────────────────
    MINIO_ENDPOINT: str = "localhost:9000"
    # Endpoint public pour les URLs pré-signées (browser-accessible).
    # Si vide, hérite de MINIO_ENDPOINT. En prod : IP/domaine public du serveur.
    MINIO_PUBLIC_ENDPOINT: str = ""
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_BUCKET_MEDIA: str = "signflow-media"
    MINIO_USE_SSL: bool = False
    # Scheme HTTPS pour les URLs pré-signées PUBLIQUES uniquement, découplé de MINIO_USE_SSL
    # (le client interne parle à MinIO en http dans Docker). À activer quand MinIO est exposé
    # derrière un reverse-proxy TLS (ex. Caddy) — sinon les médias sont mixed-content bloqués
    # depuis une page servie en HTTPS. Vide/false = comportement historique (scheme = MINIO_USE_SSL).
    MINIO_PUBLIC_USE_SSL: bool = False
    # Chiffrement SSE-S3 côté serveur — désactivé par défaut (nécessite KMS configuré sur MinIO)
    MINIO_SSE_ENABLED: bool = False

    # ── Fuseau horaire — utilisé pour évaluer les conditions schedule/event (§XX)
    # Valeur IANA valide (ex: "Europe/Paris", "America/New_York"). Défaut UTC.
    # À définir dans .env : SIGNFLOW_TZ=Europe/Paris
    SIGNFLOW_TZ: str = "UTC"

    # ── Event Bus ────────────────────────────────────────────────────────────
    EVENT_BUS_BACKEND: str = "redis_streams"

    # ── Proof of Play — archivage & rotation (§XXIV, PLAN_POP_ARCHIVAL) ───────
    # Rétention CHAUDE en base : au-delà, chaque partition JOUR est exportée vers
    # MinIO (CSV.gz + PDF + merkle_root dans cms_pop_archives) puis DROP → disque
    # rendu. Global (les partitions sont datées, partagées entre orgs).
    CMS_POP_HOT_RETENTION_DAYS: int = 90
    # Préfixe des blobs froids dans le bucket média. Un lifecycle MinIO expire ces
    # objets après la durée de conservation légale (5 ans, décision Ed) — l'index
    # cms_pop_archives (merkle_root) reste, lui, à vie. Voir PLAN_POP_ARCHIVAL §7.
    CMS_POP_ARCHIVE_PREFIX: str = "pop-archives"

    # ── Coffre-fort de secrets (chiffrement au repos — clés API BYOK §XXVII) ──
    # Clé Fernet base64 urlsafe (32 octets). Générer :
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # ⚠️ À définir dans backend ET celery-worker. La perdre = clés stockées irrécupérables.
    # Vide = coffre indisponible → les endpoints de clés IA renvoient 503.
    CMS_VAULT_KEY: str | None = None

    # ── LiteLLM ──────────────────────────────────────────────────────────────
    CMS_LITELLM_URL: str = "http://litellm:4000"
    ANTHROPIC_API_KEY: str | None = None
    CMS_LITELLM_API_KEY: str | None = None        # master key du proxy LiteLLM (si configurée)
    CMS_FEED_SUMMARY_MODEL: str = "claude-haiku-4-5"  # modèle du résumé IA des feeds (§XXV.3)

    # ── AI Assistant RAG (§XXVII) ────────────────────────────────────────────
    # Embeddings 100% locaux via Ollama (nomic-embed-text) routés par LiteLLM —
    # aucune clé API, recette éprouvée en production. Le modèle de chat de
    # l'agent reste claude-sonnet-4-6 (cloud), routé par le même proxy LiteLLM.
    CMS_EMBED_MODEL: str = "local/nomic-embed"   # nom de modèle déclaré dans docker/litellm/config.yaml
    CMS_EMBED_DIMS: int = 768                    # dimensions de nomic-embed-text (= vector(768))
    CMS_ASSISTANT_MODEL: str = "claude-sonnet-4-6"  # modèle de chat de l'agent RAG (§XXVII)
    CMS_ASSISTANT_MAX_STEPS: int = 5             # garde-fou : nb max d'étapes de l'agent LangGraph
    # Tarif blended ESTIMÉ du modèle de chat (EUR par million de tokens) pour convertir les
    # tokens consommés en coût indicatif (suivi super-admin). On ne piste que total_tokens
    # → estimation mélangée entrée+sortie ; à ajuster selon le tarif réel claude-sonnet.
    # Les embeddings sont locaux (Ollama) donc gratuits → non comptés.
    CMS_ASSISTANT_PRICE_EUR_PER_MTOK: float = 9.0

    # ── Messagerie « Jeanine » (POC Telegram — EVOLUTIONS 2026-07-08) ────────
    # Bot BotFather ; non défini = canal désactivé (webhook 503). Le secret est REQUIS :
    # il est passé à setWebhook (secret_token) et vérifié sur chaque update entrant
    # (en-tête X-Telegram-Bot-Api-Secret-Token) — sans lui, n'importe qui peut poster
    # de faux updates sur l'endpoint public.
    CMS_TELEGRAM_BOT_TOKEN: str | None = None
    CMS_TELEGRAM_WEBHOOK_SECRET: str | None = None
    CMS_TELEGRAM_API_BASE: str = "https://api.telegram.org"  # surchargable en test

    # ── SMTP ─────────────────────────────────────────────────────────────────
    # URL publique du CMS (ex. https://cms.example.com) — sert à construire
    # les liens cliquables dans les emails (lien portail annonceur). Vide = pas de lien.
    PUBLIC_WEB_URL: str = ""
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "noreply@signflow.io"
    SMTP_TLS: bool = True

    # ── Push notifications mobiles ───────────────────────────────────────────
    CMS_FCM_SERVER_KEY: str | None = None
    CMS_APNS_KEY_ID: str | None = None
    CMS_APNS_TEAM_ID: str | None = None
    CMS_APNS_PRIVATE_KEY: str | None = None

    # ── Stock Library ─────────────────────────────────────────────────────────
    UNSPLASH_ACCESS_KEY: str | None = None
    PEXELS_API_KEY: str | None = None

    # ── Feed Proxy ────────────────────────────────────────────────────────────
    FEED_PROXY_URL: str = "http://feed-proxy:8001"

    # ── Gestion des versions (§XXX) ───────────────────────────────────────────
    CMS_UPDATE_CHECK_INTERVAL: int = 3600
    CMS_UPDATE_REPO_URL: str | None = None
    CMS_UPDATE_GPG_PUBKEY: str | None = None
    CMS_UPDATE_AUTO_NOTIFY: bool = True
    CMS_UPDATE_EOL_WARN_DAYS: str = "90,30,7"

    @property
    def db_worker_url(self) -> str:
        if self.DATABASE_WORKER_URL:
            return self.DATABASE_WORKER_URL
        # Dev local : remplace le user signflow par signflow_worker
        return self.DATABASE_URL.replace(
            "signflow:signflow@", "signflow_worker:signflow_worker_secret@"
        )

    @property
    def db_app_url(self) -> str:
        if self.DATABASE_APP_URL:
            return self.DATABASE_APP_URL
        # Dev local : remplace le superuser signflow par signflow_app (soumis RLS)
        return self.DATABASE_URL.replace(
            "signflow:signflow@", "signflow_app:signflow_app_secret@"
        )

    @property
    def pool_sizes_are_explicit(self) -> bool:
        """L'exploitant a-t-il repris la main sur au moins un des quatre pools ?

        `model_fields_set` ne contient que ce qui a été FOURNI (environnement ou .env),
        jamais un défaut de classe : c'est ce qui distingue « il a écrit 10 » de « la
        valeur vaut 10 parce que personne n'a rien dit ».
        """
        return bool(
            {
                "CMS_DB_POOL_SIZE",
                "CMS_DB_MAX_OVERFLOW",
                "CMS_DB_WORKER_POOL_SIZE",
                "CMS_DB_WORKER_MAX_OVERFLOW",
            }
            & self.model_fields_set
        )

    @property
    def effective_pool_sizes(self) -> tuple[int, int, int, int]:
        """(pool, overflow, pool BYPASSRLS, overflow BYPASSRLS) réellement appliqués.

        Dès qu'un des quatre est renseigné, on respecte les quatre tels quels : un
        exploitant qui règle ses pools ne veut pas qu'on en recalcule la moitié dans son
        dos. Sinon on répartit le budget global entre les processus (cf. core/pooling.py),
        ce qui rend EXACTEMENT les valeurs historiques à un seul processus.
        """
        if self.pool_sizes_are_explicit:
            return (
                self.CMS_DB_POOL_SIZE,
                self.CMS_DB_MAX_OVERFLOW,
                self.CMS_DB_WORKER_POOL_SIZE,
                self.CMS_DB_WORKER_MAX_OVERFLOW,
            )
        return derive_pool_sizes(self.WEB_CONCURRENCY, self.CMS_DB_CONNECTION_BUDGET)


settings = Settings()
