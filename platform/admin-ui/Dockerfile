FROM node:20-alpine AS build

WORKDIR /app
COPY platform/admin-ui/package.json platform/admin-ui/package-lock.json ./
RUN npm ci
COPY platform/admin-ui/ ./
RUN npm run build

FROM nginx:1.27-alpine
COPY platform/admin-ui/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
