import "server-only";

// Same shape as backend/app/schemas.py:ProductOut.
export type Product = {
  id: number;
  title: string;
  image_url: string;
  created_at: string;
};

const TIMEOUT_MS = 5000;

export async function getProducts(): Promise<Product[]> {
  // Server-only: internal address (http://caddy/api in compose), never sent to the browser.
  const baseUrl = process.env.BACKEND_URL;
  if (!baseUrl) {
    throw new Error("BACKEND_URL is not set");
  }

  const response = await fetch(`${baseUrl.replace(/\/+$/, "")}/products`, {
    cache: "no-store",
    signal: AbortSignal.timeout(TIMEOUT_MS),
  });
  if (!response.ok) {
    throw new Error(`GET /products: HTTP ${response.status}`);
  }

  const body: unknown = await response.json();
  if (!Array.isArray(body)) {
    throw new Error("GET /products: expected a JSON array");
  }
  return body as Product[];
}
