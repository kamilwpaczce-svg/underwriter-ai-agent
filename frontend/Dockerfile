# Multi-stage build dla Next.js (output: "standalone", next.config.ts).
# Etap 6: zero zmiennych buildowych. Frontend wola wylacznie wlasny origin
# (ADRES_API = "/api" w lib/api.ts, zapiekane na stale) i to route handler
# `app/api/[...sciezka]/route.ts` przekazuje zadania do API, czytajac
# API_URL_WEWNETRZNY W CZASIE DZIALANIA (zwykla zmienna srodowiskowa runtime,
# ustawiana przy starcie kontenera / w Container Apps - nie przy buildzie).

FROM node:22-alpine AS zaleznosci
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:22-alpine AS budowanie
WORKDIR /app
COPY --from=zaleznosci /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:22-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production
ENV PORT=3000
ENV HOSTNAME=0.0.0.0

RUN addgroup --system --gid 1001 nextjs \
    && adduser --system --uid 1001 nextjs

COPY --from=budowanie /app/public ./public
COPY --from=budowanie --chown=nextjs:nextjs /app/.next/standalone ./
COPY --from=budowanie --chown=nextjs:nextjs /app/.next/static ./.next/static

USER nextjs
EXPOSE 3000

CMD ["node", "server.js"]
