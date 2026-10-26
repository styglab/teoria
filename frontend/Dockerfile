FROM node:20-alpine AS build

WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Compose combines static UI delivery and reverse proxying in one container.
FROM nginx:1.27-alpine AS gateway
COPY deploy/compose/nginx/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
RUN nginx -t
EXPOSE 80

# K3s routes APIs through Traefik; this image only serves the UI.
FROM nginx:1.27-alpine AS standalone
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
RUN nginx -t
EXPOSE 80
