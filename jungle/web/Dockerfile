# syntax=docker/dockerfile:1

# Three stages so the runtime image carries neither the source tree nor a dev
# dependency. Mirrors jungle/app/Dockerfile's shape deliberately — one build
# idiom in the repo, not two.

FROM node:22-alpine AS deps
WORKDIR /build
# Lockfile only: `npm ci` fails loudly on a lockfile that disagrees with
# package.json, which is the behaviour we want in a build.
COPY package.json package-lock.json ./
RUN npm ci

FROM node:22-alpine AS builder
ENV NEXT_TELEMETRY_DISABLED=1
WORKDIR /build
COPY --from=deps /build/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:22-alpine AS runtime
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0
# uid 10002: the app image uses 10001, so ownership stays unambiguous if a
# volume is ever shared between them.
RUN addgroup --system --gid 10002 brownbear \
 && adduser --system --uid 10002 --ingroup brownbear brownbear
WORKDIR /app
# `output: "standalone"` traces exactly the dependencies the server needs and
# emits its own server.js. Assets are NOT traced: .next/static must be copied
# alongside it, and a public/ directory would need its own COPY line — there is
# no public/ yet, so adding one means adding that line too.
COPY --from=builder --chown=brownbear:brownbear /build/.next/standalone ./
COPY --from=builder --chown=brownbear:brownbear /build/.next/static ./.next/static
USER brownbear
EXPOSE 3000
CMD ["node", "server.js"]
