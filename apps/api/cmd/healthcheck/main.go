// Command healthcheck is a tiny statically-linked HTTP GET, built solely
// so Docker's HEALTHCHECK has something to run inside the distroless
// runtime image (apps/api/Dockerfile), which has no shell, curl, or wget.
// Exits 0 on any 2xx response from the API's own /health endpoint, 1
// otherwise — the same convention `docker inspect --format '{{.State.Health.Status}}'`
// and `depends_on: condition: service_healthy` expect.
package main

import (
	"net/http"
	"os"
	"time"
)

func main() {
	client := &http.Client{Timeout: 3 * time.Second}
	resp, err := client.Get("http://localhost:8080/health")
	if err != nil {
		os.Exit(1)
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		os.Exit(1)
	}
}
