FROM golang:1.26.5 AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY main.go ./
# The build stage is Debian with glibc and the final stage is musl, so a
# binary linked against the C library dies in the final stage with a
# loader error — at `up`, not at build.
RUN CGO_ENABLED=0 go build -o /usr/local/bin/service-go .

FROM alpine:3.24.1
COPY --from=build /usr/local/bin/service-go /usr/local/bin/service-go
CMD ["service-go"]
