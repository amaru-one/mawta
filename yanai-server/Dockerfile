# Multi-stage build: compile the API and vendor the goose CLI so migrations
# can run from the same image (`docker compose run api goose ...`).
FROM golang:1.26-bookworm AS build

WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download

COPY . .
RUN CGO_ENABLED=0 go build -o /out/api ./cmd/api
RUN CGO_ENABLED=0 go install github.com/pressly/goose/v3/cmd/goose@v3.27.3

FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build /out/api /usr/local/bin/api
COPY --from=build /go/bin/goose /usr/local/bin/goose
COPY migrations /app/migrations
COPY seed /app/seed

WORKDIR /app
EXPOSE 8080
ENTRYPOINT ["/usr/local/bin/api"]
