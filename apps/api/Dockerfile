# Multi-stage build: compile with the full Go toolchain, ship only the
# static binary in a minimal, non-root runtime image.

FROM golang:1.26-bookworm AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /out/api ./cmd/api
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /out/seed ./cmd/seed

FROM gcr.io/distroless/static-debian12:nonroot AS runtime
WORKDIR /app
COPY --from=build /out/api /app/api
COPY --from=build /out/seed /app/seed
COPY internal/db/migrations /app/internal/db/migrations

# distroless/static's "nonroot" tag already runs as uid 65532 — never root.
USER nonroot:nonroot

EXPOSE 8080
ENTRYPOINT ["/app/api"]
