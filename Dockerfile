FROM node:22-bookworm-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server server
COPY skills skills
COPY --from=web /web/dist web/dist
ENV ORIEL_DATA=/data ORIEL_HOST=0.0.0.0 ORIEL_PORT=8787
EXPOSE 8787
CMD ["python", "-m", "server"]
