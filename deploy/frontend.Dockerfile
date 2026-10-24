FROM node:24-alpine AS build
WORKDIR /frontend
COPY --from=frontend package.json package-lock.json ./
RUN npm ci
COPY --from=frontend . .
ARG VITE_API_BASE_URL=/api
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

FROM nginx:stable-alpine
COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /frontend/dist /usr/share/nginx/html
EXPOSE 80
