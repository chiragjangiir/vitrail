.PHONY: help dev-up dev-down dev-logs dev-ps dev-init bucket-init test lint lint-py lint-js migrate migrate-new migrate-history migrate-current shell shell-frontend

help: ## Afficher cette aide
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

# ── Services ─────────────────────────────────────────────────────────────────

dev-up: ## Démarrer tous les services en mode dev
	docker compose up -d

dev-init: ## Initialisation complète après dev-up (migrations + bucket MinIO)
	docker compose exec backend alembic upgrade head
	docker compose exec backend python /app/scripts/create_bucket.py

bucket-init: ## Créer le bucket MinIO signflow-media
	docker compose exec backend python /app/scripts/create_bucket.py

dev-down: ## Arrêter tous les services
	docker compose down

dev-logs: ## Afficher les logs (Ctrl+C pour quitter)
	docker compose logs -f

dev-ps: ## État des services
	docker compose ps

# ── Tests ─────────────────────────────────────────────────────────────────────

test: ## Lancer les tests Python (avec coverage)
	docker compose exec backend pytest --cov=app --cov-report=term-missing -q

# ── Linting ───────────────────────────────────────────────────────────────────

lint: lint-py lint-js ## Lancer tous les linters

lint-py: ## Ruff check + format check + mypy (backend)
	docker compose exec backend ruff check app
	docker compose exec backend ruff format --check app
	docker compose exec backend mypy app --ignore-missing-imports --no-error-summary

lint-js: ## ESLint + TypeScript check (frontend)
	docker compose exec frontend npm run lint
	docker compose exec frontend npm run type-check

# ── Base de données ───────────────────────────────────────────────────────────

migrate: ## Appliquer les migrations Alembic
	docker compose exec backend alembic upgrade head

migrate-new: ## Créer une migration (MSG="description")
	docker compose exec backend alembic revision --autogenerate -m "$(MSG)"

migrate-history: ## Historique des migrations
	docker compose exec backend alembic history --verbose

migrate-current: ## Révision courante de la DB
	docker compose exec backend alembic current

# ── Shells ────────────────────────────────────────────────────────────────────

shell: ## Shell bash dans le backend
	docker compose exec backend bash

shell-frontend: ## Shell dans le frontend
	docker compose exec frontend sh
