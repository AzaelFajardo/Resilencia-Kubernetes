from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


# Inicializa la aplicacion FastAPI del microservicio.
# Este servicio se mantiene pequeno y stateless para consultar productos y revisar disponibilidad.
app = FastAPI(title="inventory-service")


# Modelo de respuesta para el endpoint de salud.
# Permite verificar de forma simple que el servicio esta levantado y responde correctamente.
class HealthResponse(BaseModel):
    status: str
    service: str


# Modelo base de producto para esta fase inicial.
# Solo incluye los campos minimos necesarios para consulta y disponibilidad.
class Product(BaseModel):
    id: int
    name: str
    sku: str
    price: float
    stock: int


# Modelo de respuesta para disponibilidad.
# Devuelve el resultado booleano y tambien el producto consultado para facilitar futuras integraciones.
class ProductAvailabilityResponse(BaseModel):
    available: bool
    product_id: int
    message: str
    product: Product


# Fuente de datos simulada en memoria.
# Se usa para evitar base de datos en esta fase y mantener el microservicio facil de probar.
# Incluye productos con stock, sin stock y uno adicional para pruebas manuales.
PRODUCTS: dict[int, Product] = {
    1: Product(
        id=1,
        name="Mechanical Keyboard",
        sku="KB-001",
        price=89.99,
        stock=12,
    ),
    2: Product(
        id=2,
        name="Wireless Mouse",
        sku="MS-002",
        price=29.99,
        stock=0,
    ),
    3: Product(
        id=3,
        name="USB-C Dock",
        sku="DK-003",
        price=119.50,
        stock=4,
    ),
}


# Funcion auxiliar que centraliza la busqueda por ID.
# Reutiliza la misma regla de negocio para ambos endpoints y devuelve 404 si el producto no existe.
def get_product_or_404(product_id: int) -> Product:
    product = PRODUCTS.get(product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


# Endpoint de salud para probes de Kubernetes o verificaciones basicas.
# Devuelve una respuesta minima con el nombre del servicio y su estado.
@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", service="inventory-service")


# Endpoint para consultar un producto por ID.
# Si el producto existe, devuelve su informacion completa; si no, responde con 404.
@app.get("/inventory/{product_id}", response_model=Product)
def get_product(product_id: int) -> Product:
    return get_product_or_404(product_id)


# Endpoint para verificar si un producto existe y tiene stock disponible.
# Mantiene 200 OK cuando el producto existe, incluso si no hay stock, porque la consulta fue resuelta correctamente.
# Solo usa 404 cuando el producto solicitado no existe en la fuente de datos simulada.
@app.get(
    "/inventory/{product_id}/availability",
    response_model=ProductAvailabilityResponse,
)
def check_availability(product_id: int) -> ProductAvailabilityResponse:
    product = get_product_or_404(product_id)

    # Si el stock es mayor que cero, se informa disponibilidad positiva.
    if product.stock > 0:
        return ProductAvailabilityResponse(
            available=True,
            product_id=product_id,
            message="Product is available",
            product=product,
        )

    # Si el producto existe pero no tiene stock, se devuelve disponibilidad negativa sin error HTTP.
    return ProductAvailabilityResponse(
        available=False,
        product_id=product_id,
        message="Product is out of stock",
        product=product,
    )
