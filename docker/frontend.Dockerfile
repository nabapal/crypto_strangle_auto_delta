# syntax=docker/dockerfile:1.6

FROM node:20-alpine AS build
WORKDIR /frontend

RUN corepack enable

COPY frontend/package.json frontend/pnpm-lock.yaml ./

RUN pnpm install --frozen-lockfile

COPY frontend .

ARG VITE_API_BASE_URL=/api
ARG VITE_ENABLE_API_DEBUG=false
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
ENV VITE_ENABLE_API_DEBUG=${VITE_ENABLE_API_DEBUG}

RUN pnpm build

FROM nginx:1.27-alpine AS runtime
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /frontend/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
