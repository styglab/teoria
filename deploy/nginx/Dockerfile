FROM nginx:1.27-alpine

COPY deploy/nginx/nginx.conf /etc/nginx/conf.d/default.conf
RUN nginx -t
