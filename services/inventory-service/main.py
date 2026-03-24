from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


# Initializes the FastAPI application for this microservice.
# This service stays small and stateless to look up products and check availability.
app = FastAPI(title="inventory-service")


# Response model for the health endpoint.
# It provides a simple way to verify that the service is running and responding correctly.
class HealthResponse(BaseModel):
    status: str
    service: str


# Base product model for this initial phase.
# It only includes the minimum fields needed for lookup and availability.
class Product(BaseModel):
    id: int
    name: str
    sku: str
    price: float
    stock: int


# Response model for availability.
# It returns the boolean result and the requested product to simplify future integrations.
class ProductAvailabilityResponse(BaseModel):
    available: bool
    product_id: int
    message: str
    product: Product


# Simulated in-memory data source.
# It avoids a database in this phase and keeps the microservice easy to test.
# It includes products with stock, without stock, and one extra item for manual checks.
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


# Helper function that centralizes lookup by ID.
# It reuses the same business rule for both endpoints and returns 404 when the product does not exist.
def get_product_or_404(product_id: int) -> Product:
    product = PRODUCTS.get(product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


# Health endpoint for Kubernetes probes or basic checks.
# It returns a minimal response with the service name and its status.
@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", service="inventory-service")


# Endpoint that retrieves a product by ID.
# If the product exists, it returns the full object; otherwise, it responds with 404.
@app.get("/inventory/{product_id}", response_model=Product)
def get_product(product_id: int) -> Product:
    return get_product_or_404(product_id)


# Endpoint that checks whether a product exists and has stock available.
# It keeps 200 OK when the product exists, even if stock is empty, because the request was resolved correctly.
# It only uses 404 when the requested product does not exist in the simulated data source.
@app.get(
    "/inventory/{product_id}/availability",
    response_model=ProductAvailabilityResponse,
)
def check_availability(product_id: int) -> ProductAvailabilityResponse:
    product = get_product_or_404(product_id)

    # If stock is greater than zero, positive availability is reported.
    if product.stock > 0:
        return ProductAvailabilityResponse(
            available=True,
            product_id=product_id,
            message="Product is available",
            product=product,
        )

    # If the product exists but has no stock, negative availability is returned without an HTTP error.
    return ProductAvailabilityResponse(
        available=False,
        product_id=product_id,
        message="Product is out of stock",
        product=product,
    )
