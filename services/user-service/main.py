from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


# Initializes the FastAPI application for this microservice.
# It stays simple because this service only exposes health, lookup, and user validation endpoints.
app = FastAPI(title="user-service")


# Response model for the health endpoint.
# It is used to confirm that the service is up and available.
class HealthResponse(BaseModel):
    status: str
    service: str


# Base user model.
# It defines the expected structure returned by lookup and validation requests.
class User(BaseModel):
    id: int
    name: str
    email: str
    role: str
    active: bool


# Response model for user validation.
# It includes the boolean result and the matching user data.
class UserValidationResponse(BaseModel):
    valid: bool
    user_id: int
    message: str
    user: User


# Simulated in-memory data source.
# It keeps the service stateless and avoids external dependencies in this first version.
# It includes three example cases: active admin, active customer, and inactive user.
USERS: dict[int, User] = {
    1: User(
        id=1,
        name="Alice Admin",
        email="alice.admin@example.com",
        role="admin",
        active=True,
    ),
    2: User(
        id=2,
        name="Carlos Cliente",
        email="carlos.cliente@example.com",
        role="customer",
        active=True,
    ),
    3: User(
        id=3,
        name="Ines Inactiva",
        email="ines.inactiva@example.com",
        role="customer",
        active=False,
    ),
}


# Helper function that centralizes lookup by ID.
# If the user does not exist, it returns 404 so the same rule can be reused across endpoints.
def get_user_or_404(user_id: int) -> User:
    user = USERS.get(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


# Health endpoint for Kubernetes probes or basic checks.
# It returns a minimal response showing that the microservice is working.
@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", service="user-service")


# Endpoint that retrieves a specific user by identifier.
# If it exists, it returns the full object; otherwise, it reuses the shared 404 response.
@app.get("/users/{user_id}", response_model=User)
def get_user(user_id: int) -> User:
    return get_user_or_404(user_id)


# Endpoint that validates whether a user exists and is active.
# It keeps 200 OK when the user exists, even if inactive, because the validation was resolved.
# It only returns 404 when the requested user does not exist in the simulated source.
@app.get("/users/{user_id}/validate", response_model=UserValidationResponse)
def validate_user(user_id: int) -> UserValidationResponse:
    user = get_user_or_404(user_id)

    # If the user is active, it is marked as valid and returned with a clear message.
    if user.active:
        return UserValidationResponse(
            valid=True,
            user_id=user_id,
            message="User is valid",
            user=user,
        )

    # If the user exists but is inactive, a negative validation is returned without using an HTTP error.
    return UserValidationResponse(
        valid=False,
        user_id=user_id,
        message="User is inactive",
        user=user,
    )
