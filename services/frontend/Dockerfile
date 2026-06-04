FROM node:20-alpine AS build

WORKDIR /app

ARG VITE_SEED_ENABLED=true
ARG VITE_SEED_USERS_COUNT=50000

ENV VITE_SEED_ENABLED=$VITE_SEED_ENABLED
ENV VITE_SEED_USERS_COUNT=$VITE_SEED_USERS_COUNT

COPY package.json ./
COPY tsconfig.json ./
COPY vite.config.ts ./
COPY index.html ./
COPY src ./src

RUN npm install
RUN npm run build

FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
