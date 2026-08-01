# SAPDemo public website - production image.
#
# Three stages, so the runtime image carries neither a compiler nor a
# node_modules tree:
#
#   deps     install exactly what package-lock.json pins
#   builder  next build, with output: 'standalone' tracing the runtime modules
#   runner   the traced server plus the static assets, running as a non-root user
#
# Build from the repository root so the build context is this directory:
#   docker build -f frontend/Dockerfile -t sapdemo-website ./frontend
#
# NEXT_PUBLIC_* values are compiled into the browser bundle at build time, which
# is why they are build arguments rather than runtime environment variables.
# Only public addresses may be passed here - a secret given to this stage would
# be readable in the shipped JavaScript.

# ---------------------------------------------------------------------------
# Stage 1 - dependencies
# ---------------------------------------------------------------------------
FROM node:22-bookworm-slim AS deps

WORKDIR /app

# Only the manifests, so this layer is reused whenever the source changes but
# the dependencies do not.
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

# ---------------------------------------------------------------------------
# Stage 2 - build
# ---------------------------------------------------------------------------
FROM node:22-bookworm-slim AS builder

WORKDIR /app

ENV NEXT_TELEMETRY_DISABLED=1

ARG NEXT_PUBLIC_SITE_URL=""
ARG NEXT_PUBLIC_DEMO_URL=""
ARG NEXT_PUBLIC_CONTACT_EMAIL=""
ARG NEXT_PUBLIC_REPOSITORY_URL=""
ARG NEXT_PUBLIC_LOCATION_LABEL=""

ENV NEXT_PUBLIC_SITE_URL=${NEXT_PUBLIC_SITE_URL} \
    NEXT_PUBLIC_DEMO_URL=${NEXT_PUBLIC_DEMO_URL} \
    NEXT_PUBLIC_CONTACT_EMAIL=${NEXT_PUBLIC_CONTACT_EMAIL} \
    NEXT_PUBLIC_REPOSITORY_URL=${NEXT_PUBLIC_REPOSITORY_URL} \
    NEXT_PUBLIC_LOCATION_LABEL=${NEXT_PUBLIC_LOCATION_LABEL}

COPY --from=deps /app/node_modules ./node_modules
COPY . .

RUN npm run build

# ---------------------------------------------------------------------------
# Stage 3 - runtime
# ---------------------------------------------------------------------------
FROM node:22-bookworm-slim AS runner

LABEL org.opencontainers.image.title="SAPDemo website" \
      org.opencontainers.image.description="Public marketing website for SAPDemo, an SAP-focused demonstration platform running on fictional data. Not affiliated with SAP."

WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

# wget is used by the container healthcheck below. It is in the base image
# already; this line documents the dependency rather than installing it.

# The node image ships a `node` user (uid 1000). Reusing it avoids creating an
# account and keeps the image free of shadow-file churn.
COPY --from=builder --chown=node:node /app/.next/standalone ./
COPY --from=builder --chown=node:node /app/.next/static ./.next/static

# `public/` is optional - Next only creates it if the project has one. Copying a
# directory that may not exist would fail the build, so it is deliberately not
# copied here; add a COPY line if static assets are introduced.

USER node

EXPOSE 3000

# HOSTNAME=0.0.0.0 binds inside the container only. The port is not published
# on the host by the self-hosted compose file - the tunnel reaches this service
# over the private Docker network by name.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD node -e "fetch('http://127.0.0.1:3000/').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

CMD ["node", "server.js"]
