FROM nginx:1.27-alpine

COPY deploy/compose/nginx/nginx.conf /etc/nginx/conf.d/default.conf
RUN nginx -t
