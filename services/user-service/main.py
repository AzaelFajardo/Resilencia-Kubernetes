from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


# Inicializa la aplicacion FastAPI del microservicio.
# Se mantiene simple porque este servicio solo expone salud, consulta y validacion de usuarios.
app = FastAPI(title="user-service")


# Modelo de respuesta para el endpoint de salud.
# Sirve para confirmar que el servicio esta levantado y disponible.
class HealthResponse(BaseModel):
    status: str
    service: str


# Modelo base de usuario.
# Define la estructura esperada que se devuelve en las consultas y validaciones.
class User(BaseModel):
    id: int
    name: str
    email: str
    role: str
    active: bool


# Modelo de respuesta para la validacion de usuarios.
# Incluye el resultado booleano y tambien los datos del usuario encontrado.
class UserValidationResponse(BaseModel):
    valid: bool
    user_id: int
    message: str
    user: User


# Fuente de datos simulada en memoria.
# Se usa para mantener el servicio stateless y evitar dependencias externas en esta primera version.
# Incluye tres casos de ejemplo: administrador activo, cliente activo y usuario inactivo.
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


# Funcion auxiliar para centralizar la busqueda por ID.
# Si el usuario no existe, responde con 404 para reutilizar la misma regla en varios endpoints.
def get_user_or_404(user_id: int) -> User:
    user = USERS.get(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


# Endpoint de salud para probes de Kubernetes o verificaciones basicas.
# Devuelve una respuesta minima que indica que el microservicio esta funcionando.
@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", service="user-service")


# Endpoint para consultar un usuario especifico por su identificador.
# Si existe, devuelve el objeto completo; si no existe, reutiliza la respuesta 404 comun.
@app.get("/users/{user_id}", response_model=User)
def get_user(user_id: int) -> User:
    return get_user_or_404(user_id)


# Endpoint para validar si un usuario existe y si esta activo.
# Mantiene 200 OK cuando el usuario existe, incluso si esta inactivo, porque la validacion fue resuelta.
# Solo devuelve 404 cuando el usuario solicitado no existe en la fuente simulada.
@app.get("/users/{user_id}/validate", response_model=UserValidationResponse)
def validate_user(user_id: int) -> UserValidationResponse:
    user = get_user_or_404(user_id)

    # Si el usuario esta activo, se marca como valido y se devuelve un mensaje claro.
    if user.active:
        return UserValidationResponse(
            valid=True,
            user_id=user_id,
            message="User is valid",
            user=user,
        )

    # Si el usuario existe pero esta inactivo, se devuelve validacion negativa sin usar error HTTP.
    return UserValidationResponse(
        valid=False,
        user_id=user_id,
        message="User is inactive",
        user=user,
    )
