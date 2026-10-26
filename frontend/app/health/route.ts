// Liveness for the Docker healthcheck. Doesn't call the backend: a backend outage
// must not mark frontend replicas unhealthy (the page shows an error message instead).
export const dynamic = "force-dynamic";

export function GET() {
  return Response.json({ status: "ok" });
}
