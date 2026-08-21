# One Dockerfile, two apps: `--build-arg APP=cms|viewer`.
#
# The workspace is copied whole because both apps import `shared/`, and pnpm's store is
# cached so a change in one app does not re-download the other's dependencies.
FROM node:22-alpine AS build
ARG APP
# Vite inlines env at build time, so the API URL is baked into the bundle here. It is the
# browser's view of the API, not the container's — hence localhost, not the service name.
ARG VITE_API_BASE_URL=http://localhost:8000
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

# Pinned, not "latest": the lockfile was produced by a specific pnpm, and a newer one
# rejects it outright under its own install policies.
RUN corepack enable && corepack prepare pnpm@10.25.0 --activate
WORKDIR /app

COPY frontend/pnpm-workspace.yaml frontend/package.json frontend/pnpm-lock.yaml ./
COPY frontend/shared/package.json ./shared/
COPY frontend/cms/package.json ./cms/
COPY frontend/viewer/package.json ./viewer/
RUN --mount=type=cache,id=pnpm,target=/pnpm/store \
    pnpm config set store-dir /pnpm/store && pnpm install --frozen-lockfile

COPY frontend/ ./
RUN pnpm --filter "@peblo/$APP" build

FROM nginx:1.27-alpine AS runtime
ARG APP
COPY --from=build /app/$APP/dist /usr/share/nginx/html
# A single-page app: every unknown path is the app's own route, not a 404.
RUN printf 'server {\n\
  listen 80;\n\
  root /usr/share/nginx/html;\n\
  location / { try_files $uri $uri/ /index.html; }\n\
  location ~* \\.(js|css|jpg|png|svg|woff2)$ { expires 7d; add_header Cache-Control "public"; }\n\
}\n' > /etc/nginx/conf.d/default.conf
EXPOSE 80
