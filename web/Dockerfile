# syntax=docker/dockerfile:1
# Health Briefing web UI: Next.js standalone server, non-root.
#
#   docker build -t health-briefing-web --build-arg API_BASE_URL=http://api:8080 .
#   docker run -p 3000:3000 health-briefing-web
#
# API_BASE_URL is baked into the /api/* rewrite at build time (Next.js evaluates
# rewrites during `next build`). Use --build-arg NEXT_PUBLIC_API_MODE=mock for a
# backend-free demo image.

FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

FROM node:22-alpine AS build
WORKDIR /app
ARG API_BASE_URL=http://api:8080
ARG NEXT_PUBLIC_API_MODE=api
ENV API_BASE_URL=${API_BASE_URL} \
    NEXT_PUBLIC_API_MODE=${NEXT_PUBLIC_API_MODE} \
    NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 \
    PORT=3000
COPY --from=build --chown=node:node /app/.next/standalone ./
COPY --from=build --chown=node:node /app/.next/static ./.next/static
USER node
EXPOSE 3000
CMD ["node", "server.js"]
