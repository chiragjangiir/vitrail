FROM node:20-alpine AS base

# ── Dépendances ───────────────────────────────────────────────────────────────
# ⚠️ Deps COMPLÈTES (pas de --omit=dev) : tailwindcss, postcss, autoprefixer et
# typescript sont en devDependencies et sont REQUIS par `next build`. Les omettre
# faisait échouer le stage `builder` — c'est pourquoi la cible `runner` n'a jamais
# servi et que la prod buildait au démarrage du conteneur. Le standalone ne trace
# que les modules réellement importés au runtime : rien de tout ça n'atterrit dans
# l'image finale.
FROM base AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci

# ── Build production ──────────────────────────────────────────────────────────
FROM base AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# Les NEXT_PUBLIC_* sont INLINÉS dans le bundle AU BUILD, pas lus au runtime : la
# valeur présente ici est gravée dans l'image. Vide = URL d'API RELATIVE (`/api/v1`
# sur la même origine), seule valeur correcte pour une image distribuée — le
# navigateur du client appelle l'hôte qui lui a servi la page, quel qu'il soit.
# Une valeur absolue ferait appeler CETTE adresse depuis tous les clients.
ARG NEXT_PUBLIC_API_URL=""
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}
RUN npm run build

# ── Image de dev (montée en volume dans docker-compose) ───────────────────────
FROM base AS dev
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install
COPY . .
EXPOSE 3000
CMD ["npm", "run", "dev"]

# ── Image de production (standalone Next.js) ──────────────────────────────────
FROM base AS runner
WORKDIR /app
ENV NODE_ENV=production
# server.js (standalone) écoute HOSTNAME:PORT — 0.0.0.0 explicite pour être joignable
# depuis le réseau du conteneur (nginx/Caddy en amont), pas seulement en loopback.
ENV HOSTNAME=0.0.0.0
ENV PORT=3000
RUN addgroup --system --gid 1001 nodejs && adduser --system --uid 1001 nextjs
COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
USER nextjs
EXPOSE 3000
CMD ["node", "server.js"]
