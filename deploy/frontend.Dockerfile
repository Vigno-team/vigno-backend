FROM node:24.22.2-alpine3.23 AS build
WORKDIR /frontend
COPY --from=frontend package.json package-lock.json ./
RUN npm ci
COPY --from=frontend . .
ARG VITE_API_BASE_URL=/api
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.28.2-alpine3.23
COPY deploy/nginx.conf /etc/nginx/templates/default.conf.template
COPY deploy/security-headers.conf /etc/nginx/security-headers.conf
COPY --from=build /frontend/dist /usr/share/nginx/html
# envsubst escribe sólo en /tmp, incluso con el filesystem de solo lectura.
ENV NGINX_ENVSUBST_OUTPUT_DIR=/tmp NGINX_ENVSUBST_FILTER="^(HTTPS_PORT|SECURE_HSTS_SECONDS)$"
USER root
RUN sed -i 's|/etc/nginx/conf.d/\*.conf|/tmp/*.conf|; s/worker_processes  auto;/worker_processes  2;/' /etc/nginx/nginx.conf
USER nginx
EXPOSE 8080 8443
