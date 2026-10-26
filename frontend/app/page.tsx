import { getProducts, type Product } from "@/lib/backend";

// Render on every request: no build-time prerender, no shared cache between replicas.
export const dynamic = "force-dynamic";

export default async function CatalogPage() {
  let products: Product[];
  try {
    products = await getProducts();
  } catch (error) {
    console.error("Failed to load products", error);
    return (
      <main>
        <h1>Каталог</h1>
        <p>Не удалось загрузить каталог. Попробуйте обновить страницу позже.</p>
      </main>
    );
  }

  return (
    <main>
      <h1>Каталог</h1>
      {products.length === 0 ? (
        <p>Товаров пока нет</p>
      ) : (
        <ul>
          {products.map((product) => (
            <li key={product.id}>
              {/* Plain <img>: next/image's optimizer would cache on each replica's disk. */}
              <img src={product.image_url} alt={product.title} width={200} loading="lazy" />
              <p>{product.title}</p>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
