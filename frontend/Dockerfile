FROM node:22-slim AS build
WORKDIR /app
# rewrites (/api -> backend) are resolved at build time
ARG BACKEND_URL=http://api:8000
ENV BACKEND_URL=$BACKEND_URL
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM node:22-slim
WORKDIR /app
ENV NODE_ENV=production
COPY --from=build /app ./
EXPOSE 3000
CMD ["npm", "run", "start"]
