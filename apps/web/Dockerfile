FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json ./
RUN npm install
FROM node:22-alpine AS build
WORKDIR /app
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
ARG LIFE_PILOT_COMMIT_SHA
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build
FROM node:22-alpine
WORKDIR /app
ENV NODE_ENV=production
ARG LIFE_PILOT_COMMIT_SHA
ENV LIFE_PILOT_COMMIT_SHA=$LIFE_PILOT_COMMIT_SHA
LABEL org.opencontainers.image.revision=$LIFE_PILOT_COMMIT_SHA
COPY --from=build /app ./
EXPOSE 3000
CMD ["npm", "run", "start"]
