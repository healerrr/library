FROM node:22-alpine AS builder
WORKDIR /app
ARG NUXT_PUBLIC_API_BASE=/api
ARG NUXT_API_PROXY_TARGET=http://backend:8000/api
ENV NUXT_PUBLIC_API_BASE=$NUXT_PUBLIC_API_BASE \
    NUXT_API_PROXY_TARGET=$NUXT_API_PROXY_TARGET
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production \
    HOST=0.0.0.0 \
    PORT=3000 \
    NUXT_PUBLIC_API_BASE=/api \
    NUXT_API_PROXY_TARGET=http://backend:8000/api
COPY --from=builder --chown=node:node /app/.output ./.output
USER node
EXPOSE 3000
CMD ["node", ".output/server/index.mjs"]
