# syntax=docker/dockerfile:1
#
# SmartDoc Formatter's frontend (корекции.docx §67): a production build served by
# Next's minimal standalone server.
#
#   docker build -t smartdoc-frontend --build-arg NEXT_PUBLIC_API_BASE_URL=https://api.example.com frontend
#
# NEXT_PUBLIC_API_BASE_URL is the API's address as the browser sees it; it is built
# into the pages (and the Content-Security-Policy). At run time, API_INTERNAL_URL is
# where the Next server itself reaches the API when that differs (e.g. http://backend:8000).

FROM node:24-slim AS deps
WORKDIR /app
COPY package.json package-lock.json ./
# Exactly the locked versions.
RUN npm ci

FROM node:24-slim AS build
WORKDIR /app
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL \
    NEXT_OUTPUT=standalone \
    NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:24-slim AS run
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0
COPY --from=build --chown=node:node /app/.next/standalone ./
COPY --from=build --chown=node:node /app/.next/static ./.next/static
COPY --from=build --chown=node:node /app/public ./public
# The node image's own unprivileged user.
USER node
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["node", "-e", "fetch('http://127.0.0.1:3000/login').then((r) => process.exit(r.ok ? 0 : 1)).catch(() => process.exit(1))"]
CMD ["node", "server.js"]
