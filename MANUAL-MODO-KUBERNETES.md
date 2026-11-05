
# Manual de usuario - Modo Kubernetes

Este manual explica como dejar funcionando el modo Kubernetes del panel de control.
Esta escrito para alguien que ya tiene el proyecto clonado.
Esta pensado para Linux y macOS.
Incluye el arranque automatico y el arranque manual.

---

## 1. Que es el modo Kubernetes

El panel de control puede trabajar de dos formas.

- `Compose`: habla con los contenedores de Docker Compose.
- `Kubernetes`: habla con el cluster de minikube usando la API de Kubernetes.

El boton o selector de modo en el panel solo cambia el destino de las llamadas.
No crea pods. No despliega el proyecto. No configura certificados.

Por eso el orden correcto siempre es este.

1. Preparar el cluster.
2. Desplegar los manifiestos.
3. Levantar el panel.
4. Cambiar el modo a Kubernetes al final.

Si cambias el modo antes de preparar el cluster vas a ver errores de conexion o de autenticacion.

---

## 2. Lo que necesitas antes de empezar

| Herramienta | Para que sirve | Valor probado en este proyecto |
| --- | --- | --- |
| Docker | Ejecutar contenedores | Docker 29.6 en Linux o Docker Desktop en macOS |
| Docker Compose | Levantar el panel y la observabilidad | Compose 5.1 |
| minikube | Crear el cluster local | minikube 1.38 |
| kubectl | Administrar el cluster | kubectl 1.37 |
| curl | Probar la API del panel | cualquiera |
| Navegador | Abrir el panel | Chrome, Firefox o Edge |

minikube y kubectl no vienen con el proyecto.
Son requisitos externos y deben estar instalados y disponibles en el `PATH`.
El proyecto no los instala por ti.

En macOS se instalan con Homebrew.

```bash
brew install minikube
brew install kubectl
```

En Linux puedes instalar minikube y kubectl con los binarios oficiales.

```bash
curl -LO https://storage.googleapis.com/minikube/releases/latest/minikube-linux-amd64
sudo install minikube-linux-amd64 /usr/local/bin/minikube

curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
sudo install kubectl /usr/local/bin/kubectl
```

Si usas otra arquitectura o distribucion revisa la guia oficial de instalacion.
Tambien puedes usar el gestor de paquetes de tu sistema.

Verifica que las herramientas respondan antes de continuar.

```bash
minikube version
kubectl version --client
docker compose version
```

Tambien necesitas esto.

- Docker encendido. En macOS abre Docker Desktop antes de empezar.
- Al menos 2 CPUs y 4 GB de RAM libres para minikube.
  En macOS esos recursos se reservan desde Docker Desktop en Settings > Resources.
- Espacio en disco para las imagenes.
- Los puertos `8105`, `8443` y los puertos del cluster libres.
- El proyecto clonado y abierto en una terminal.

---

## 3. Arranque recomendado en Linux o macOS

Sigue estos pasos en este orden.
No ejecutes `./run.sh k8s` antes de terminar los pasos 1 2 y 3.

### 3.1 Paso 1: arrancar minikube una vez

Esto genera los certificados y deja el cluster listo.
Tambien sirve para conocer la direccion del API server.

```bash
minikube start --driver=docker
minikube addons enable metrics-server
```

Obten la direccion del API server.

```bash
kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}'
echo
```

En Linux normalmente es esta.

```text
https://192.168.49.2:8443
```

En macOS con Docker Desktop puede ser esta.

```text
https://127.0.0.1:PUERTO
```

### 3.2 Paso 2: copiar los certificados

Los certificados los genera minikube.
No vienen en el repositorio.
El script del proyecto solo revisa que existan. No los genera.

```bash
mkdir -p k8s/certs
cp ~/.minikube/ca.crt k8s/certs/ca.crt
cp ~/.minikube/profiles/minikube/client.crt k8s/certs/client.crt
cp ~/.minikube/profiles/minikube/client.key k8s/certs/client.key
chmod 600 k8s/certs/client.key
```

Repite esta copia si borras el cluster con `minikube delete` y lo creas de nuevo.

### 3.3 Paso 3: configurar K8S_API_SERVER en .env

Abre `.env` en la raiz del proyecto.
Busca la linea `K8S_API_SERVER` y pon la direccion que obtuviste en el paso 1.

En Linux normalmente queda asi.

```env
K8S_API_SERVER=https://192.168.49.2:8443
```

En macOS no uses `127.0.0.1`.
El panel corre dentro de un contenedor y ese `127.0.0.1` seria el propio contenedor.
Cambia `127.0.0.1` por `host.docker.internal` y conserva el puerto.

```env
K8S_API_SERVER=https://host.docker.internal:PUERTO
```

Todavia no hace falta recrear el panel.
El panel aun no esta levantado y el script lo creara con este valor.

### 3.4 Paso 4: ejecutar el script

Ya con los certificados copiados y `.env` configurado ejecuta el script.

```bash
cd /ruta/al/proyecto
./run.sh k8s
```

El script hace todo esto en orden.

1. Revisa o arranca minikube con el driver Docker.
2. Habilita `metrics-server` para que funcione el HPA.
3. Construye las imagenes de los 5 microservicios y del seeder.
4. Carga las imagenes dentro de minikube.
5. Revisa los certificados en `k8s/certs/`.
6. Aplica `k8s/base/` y `k8s/resilience/hpa.yaml`.
7. Espera los rollouts y el job `data-seeder`.
8. Levanta Docker Compose con el panel y la observabilidad.
9. Cambia el panel a modo Kubernetes.

Cuando termine debes ver algo parecido a esto.

```text
[ok] control-panel responde
[ok] control-panel en modo kubernetes
```

Si el script falla revisa la seccion 8 de problemas comunes.

---

## 4. Arranque manual paso a paso

Usa esta seccion si prefieres hacer el proceso a mano.

### 4.1 Arrancar Docker y minikube

Primero confirma que Docker responde.
En macOS abre Docker Desktop y espera a que termine de iniciar.

```bash
docker info
```

Luego arranca minikube.

```bash
minikube start --driver=docker
```

Si el equipo tiene recursos limitados puedes reservar mas memoria.

```bash
minikube start --driver=docker --cpus=4 --memory=6144
```

Verifica que el cluster este arriba.

```bash
minikube status
kubectl get nodes
```

Debes ver el nodo `minikube` en estado `Ready`.

### 4.2 Habilitar metrics-server

El HPA necesita leer el consumo de CPU.
Sin este addon el HPA muestra `unknown` y no escala.

```bash
minikube addons enable metrics-server
```

Espera un minuto y verifica.

```bash
kubectl top nodes
```

Si responde con CPU y memoria esta listo.

### 4.3 Copiar los certificados al proyecto

Estos certificados los genera minikube en tu maquina.
No forman parte del repositorio.
En el repositorio solo existe `k8s/certs/.gitkeep`.
Por eso hay que copiarlos desde tu instalacion de minikube.

```bash
mkdir -p k8s/certs
cp ~/.minikube/ca.crt k8s/certs/ca.crt
cp ~/.minikube/profiles/minikube/client.crt k8s/certs/client.crt
cp ~/.minikube/profiles/minikube/client.key k8s/certs/client.key
chmod 600 k8s/certs/client.key
```

Repite esta copia si alguna vez borras el cluster con `minikube delete` y lo creas de nuevo.

### 4.4 Configurar la direccion del API server

Abre el archivo `.env` en la raiz del proyecto.
Busca la linea `K8S_API_SERVER` y dejala con la direccion real de tu cluster.

Primero obten la direccion.

```bash
kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}'
echo
```

En Linux con driver Docker normalmente responde esto.

```text
https://192.168.49.2:8443
```

En ese caso tu `.env` debe tener esta linea.

```env
K8S_API_SERVER=https://192.168.49.2:8443
```

En macOS con Docker Desktop el comando puede responder algo como esto.

```text
https://127.0.0.1:52345
```

En ese caso no uses `127.0.0.1`.
El panel corre dentro de un contenedor y ese `127.0.0.1` seria el propio contenedor.
Cambia `127.0.0.1` por `host.docker.internal` y conserva el puerto que mostro el comando.

```env
K8S_API_SERVER=https://host.docker.internal:52345
```

En macOS el puerto puede cambiar cada vez que reinicias minikube.
Si cambia debes actualizar `.env` y recrear el panel.

Si tu cluster usa otra direccion o otro puerto debes usar ese valor.
Si cambiaste `.env` ejecuta esto para que el panel lea el nuevo valor.

```bash
docker compose up -d --force-recreate control-panel
```

### 4.5 Construir y cargar las imagenes

Kubernetes usara las imagenes locales del cluster.
Por eso hay que construir y cargar cada imagen dentro de minikube.

```bash
for s in order user inventory payment notification; do
  docker build -q -t "${s}-service:latest" -f "services/${s}-service/Dockerfile" services
  minikube image load "${s}-service:latest"
done
docker build -q -t data-seeder:latest -f services/data-seeder/Dockerfile .
minikube image load data-seeder:latest
```

Verifica que las imagenes esten dentro del cluster.

```bash
minikube image ls | grep service
```

### 4.6 Aplicar los manifiestos

```bash
kubectl apply -f k8s/base/
kubectl apply -f k8s/resilience/hpa.yaml
```

Espera a que los deployments esten listos.

```bash
kubectl rollout status deployment/postgres
kubectl rollout status deployment/postgres-replica
kubectl rollout status deployment/user-service
kubectl rollout status deployment/inventory-service
kubectl rollout status deployment/payment-service
kubectl rollout status deployment/notification-service
kubectl rollout status deployment/order-service
kubectl wait --for=condition=complete job/data-seeder --timeout=180s
```

Revisa que todos los pods esten en `Running`.

```bash
kubectl get pods
```

### 4.7 Levantar el panel y la observabilidad

El panel vive en Docker Compose.
Por eso necesitas levantar Compose aunque el modo sea Kubernetes.

```bash
docker compose up -d --remove-orphans
```

Espera unos segundos y prueba el panel.

```bash
curl -s http://localhost:8105/api/runtime-mode
```

Debe responder algo asi.

```json
{"mode":"compose","k8s_configured":true,"k8s_reachable":true}
```

Si `k8s_reachable` es `false` revisa la direccion del API server y los certificados.

### 4.8 Cambiar el modo a Kubernetes

Puedes hacerlo desde la interfaz o desde la terminal.

Desde la interfaz.

1. Abre `http://localhost:8105`.
2. En la pestana Inicio busca el selector de entorno.
3. Elige `Kubernetes`.
4. Confirma el cambio.

Desde la terminal.

```bash
curl -s -X POST \
  -H 'Content-Type: application/json' \
  -d '{"mode":"kubernetes"}' \
  http://localhost:8105/api/runtime-mode
```

La respuesta esperada es esta.

```json
{"mode":"kubernetes","k8s_configured":true,"k8s_reachable":true}
```

---

## 5. Verificacion final

Ejecuta estas comprobaciones.

```bash
minikube status
kubectl get pods
kubectl get hpa
curl -s http://localhost:8105/api/runtime-mode
```

Debes ver esto.

- `minikube status` con `host`, `kubelet` y `apiserver` en `Running`.
- Todos los pods de los servicios en `Running` y `1/1`.
- Los HPA `order-service-hpa` y `payment-service-hpa` con CPU y replicas.
- El panel en modo `kubernetes` con `k8s_reachable: true`.

Tambien puedes probar el panel.

```bash
curl -s http://localhost:8105/api/health
curl -s http://localhost:8105/api/kubernetes
```

Si `api/health` muestra los 5 servicios en `up: true` y `api/kubernetes` muestra `reachable: true` el modo Kubernetes esta funcionando.

---

## 6. Como usar el panel en modo Kubernetes

Abre `http://localhost:8105`.

En la pestana Inicio puedes hacer esto.

- Ver la salud de los 5 servicios.
- Ver el lider actual de la orquestacion.
- Poner ordenes de prueba.
- Ver las replicas de cada servicio.
- Escalar un Deployment a mano.
- Borrar un pod para probar la auto-recuperacion.

En la pestana Kubernetes puedes hacer esto.

- Ver pods y su estado.
- Ver reinicios por pod.
- Ver el HPA y las replicas actuales.
- Borrar un pod.
- Ver un historico de replicas.

Para una demostracion rapida puedes hacer esto.

1. Entra a la pestana Pruebas.
2. Lanza una simulacion de trafico.
3. Ve a la pestana Kubernetes.
4. Observa como el HPA sube las replicas de `order-service` y `payment-service`.
5. Deten la simulacion.
6. Espera unos minutos y observa como bajan las replicas.

Para probar auto-recuperacion.

1. Entra a la pestana Kubernetes.
2. Elige un pod de `order-service`.
3. Borralo.
4. Kubernetes crea uno nuevo de inmediato.
5. La pestana Inicio sigue funcionando.

Importante: el cluster tiene su propia base de datos.
Los datos de Kubernetes no son los mismos que los de Compose.
Si quieres datos para la demo puedes generarlos desde las pestanas Clientes e Inventario del panel cuando ya estes en modo Kubernetes.

---

## 7. Detener y volver a arrancar

Para detener todo.

```bash
./run.sh stop
```

Eso detiene Docker Compose y minikube sin borrar datos.

Para volver a arrancar todo.

```bash
./run.sh k8s
```

En Linux la direccion del API server no cambia.
En macOS el puerto puede cambiar al arrancar minikube de nuevo.
En ese caso arranca minikube primero y revisa la direccion.

```bash
minikube start --driver=docker
kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}'
echo
```

Si el puerto cambio actualiza `K8S_API_SERVER` en `.env` y despues ejecuta `./run.sh k8s`.

Para detener solo contenedores y dejar el cluster arriba.

```bash
./run.sh stop --keep-cluster
```

Recuerda algo importante.
El modo Kubernetes vive en la memoria del panel.
Cada vez que reinicies o recrees el `control-panel` vuelve a modo Compose.
Despues de reiniciar el panel tienes que cambiar el modo otra vez.

---

## 8. Problemas comunes y como corregirlos

### 8.1 El panel conserva un K8S_API_SERVER viejo

Sintoma.
El panel sigue mostrando `k8s_reachable: false` o un error de conexion aunque ya corregiste `.env`.

Causa.
El valor de `K8S_API_SERVER` se copia al contenedor cuando se crea.
Editar `.env` no cambia un contenedor que ya esta corriendo.

Comprueba el valor que tiene el contenedor.

```bash
docker compose exec control-panel sh -c 'echo $K8S_API_SERVER'
```

Si el valor no coincide con tu `.env` corrigelo asi.

```bash
# 1. Edita .env con la direccion correcta
# 2. Recrea el panel para que lea el nuevo valor
docker compose up -d --force-recreate control-panel
```

`docker compose restart control-panel` no sirve para este caso.
Ese comando reinicia el contenedor pero conserva las variables viejas.

Despues de recrear el panel el modo vuelve a Compose.
Cambia otra vez a Kubernetes desde la interfaz o con este comando.

```bash
curl -s -X POST \
  -H 'Content-Type: application/json' \
  -d '{"mode":"kubernetes"}' \
  http://localhost:8105/api/runtime-mode
```

Verifica el resultado.

```bash
curl -s http://localhost:8105/api/runtime-mode
```

Debe aparecer `"mode":"kubernetes"` y `"k8s_reachable":true`.

### 8.2 Ejecutaste el script antes de configurar .env

Sintoma.
`./run.sh k8s` termino y mostro `[ok] control-panel en modo kubernetes` pero `k8s_reachable` sigue en `false`.
Tambien puede aparecer el aviso `no se pudo activar el modo kubernetes`.

Causa.
El panel se creo con `K8S_API_SERVER` vacio o con un valor viejo.
El script no valida la conexion real. Solo confirma que el panel acepto el cambio de modo.

Correccion.
No hace falta repetir minikube ni los manifiestos.
Solo corrige `.env` recrea el panel y cambia el modo otra vez.

```bash
# edita .env
docker compose up -d --force-recreate control-panel
curl -s -X POST \
  -H 'Content-Type: application/json' \
  -d '{"mode":"kubernetes"}' \
  http://localhost:8105/api/runtime-mode
```

Confirma que ahora si hay conexion.

```bash
curl -s http://localhost:8105/api/runtime-mode
```

Debe aparecer `"k8s_reachable":true`.
Para evitar este problema sigue el orden de la seccion 3.

### 8.3 Faltan los certificados o son de otro cluster

Sintoma.
Errores como `401 Unauthorized`, `403 Forbidden`, `x509: certificate signed by unknown authority` o `SSL: CERTIFICATE_VERIFY_FAILED`.

Causa.
Los certificados no existen en `k8s/certs/` o son de otro cluster.

Correccion.
Vuelve a copiar los tres archivos desde tu minikube actual.

```bash
cp ~/.minikube/ca.crt k8s/certs/ca.crt
cp ~/.minikube/profiles/minikube/client.crt k8s/certs/client.crt
cp ~/.minikube/profiles/minikube/client.key k8s/certs/client.key
chmod 600 k8s/certs/client.key
```

Los certificados se montan desde el host.
Si el panel sigue fallando recrea el contenedor y cambia el modo otra vez.

### 8.4 En macOS cambio el puerto del API server

Sintoma.
En macOS el panel dejo de conectar despues de reiniciar minikube.

Causa.
El puerto del API server cambia con algunos arranques de minikube.

Correccion.
Vuelve a leer la direccion actual.

```bash
kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}'
echo
```

Actualiza `.env` usando `host.docker.internal` y el puerto nuevo.

```env
K8S_API_SERVER=https://host.docker.internal:PUERTO_NUEVO
```

Luego recrea el panel y cambia el modo otra vez.

```bash
docker compose up -d --force-recreate control-panel
curl -s -X POST \
  -H 'Content-Type: application/json' \
  -d '{"mode":"kubernetes"}' \
  http://localhost:8105/api/runtime-mode
```

### 8.5 El modo vuelve a Compose solo

Sintoma.
El panel estaba en Kubernetes y despues de un rato aparece en Compose.

Causa.
El modo vive en la memoria del panel.
Si el `control-panel` se reinicia vuelve a Compose.

Correccion.
Solo cambia el modo otra vez desde la interfaz o con el comando de la seccion 4.8.

### 8.6 minikube no arranca por Address already in use

Sintoma.
`minikube start` falla con `Address already in use`.

Causa.
El `control-panel` tomo la IP `192.168.49.2` porque minikube estaba apagado.

Correccion.
Hazlo en este orden.

```bash
docker compose stop control-panel
docker start minikube
minikube start
docker compose start control-panel
```

### 8.7 El HPA no escala

Sintoma.
El HPA muestra `unknown` en CPU o las replicas no suben.

Causa.
Falta `metrics-server` o el panel no tiene carga suficiente.

Correccion.

```bash
minikube addons enable metrics-server
kubectl top pods
```

Espera uno o dos minutos y vuelve a lanzar la simulacion de trafico.

### 8.8 Los pods no arrancan por ErrImageNeverPull

Sintoma.
Los pods quedan en `ErrImageNeverPull` o `ImagePullBackOff`.

Causa.
Las imagenes no estan cargadas dentro de minikube.

Correccion.
Repite la construccion y carga de imagenes de la seccion 4.5.
Despues reinicia los deployments.

```bash
kubectl rollout restart deployment/order-service
kubectl rollout restart deployment/user-service
kubectl rollout restart deployment/inventory-service
kubectl rollout restart deployment/payment-service
kubectl rollout restart deployment/notification-service
```

### 8.9 Tabla de referencia rapida

| Mensaje o sintoma | Causa probable | Solucion |
| --- | --- | --- |
| `Kubernetes not configured (set K8S_API_SERVER and mount certs in k8s/certs/)` | `K8S_API_SERVER` vacio o el panel no se recreo | Configura `.env` y ejecuta `docker compose up -d --force-recreate control-panel` |
| `Kubernetes no esta configurado` en el panel | Igual que el caso anterior | Revisa `.env` y recrea el panel |
| `cluster unreachable: Connection refused` | minikube apagado o direccion incorrecta | Ejecuta `minikube status` y corrige `K8S_API_SERVER` |
| En macOS el panel no conecta al cluster | Se uso `127.0.0.1` en `.env` o el puerto cambio | Usa `host.docker.internal` con el puerto actual y recrea el panel |
| `cluster unreachable: [SSL: CERTIFICATE_VERIFY_FAILED]` | Certificados viejos o de otro cluster | Vuelve a copiar los certificados de la seccion 4.3 |
| `x509: certificate signed by unknown authority` | `ca.crt` no corresponde al cluster actual | Copia de nuevo `ca.crt` |
| `401 Unauthorized` o `403 Forbidden` | Certificado de cliente incorrecto o sin permisos | Copia de nuevo `client.crt` y `client.key` y recrea el panel |
| `no orchestrator leader reachable` | Los pods no estan listos o no hay lider | Espera un minuto y revisa `kubectl get pods` |
| `not the current orchestrator leader` | Cambio de lider en curso | Espera 5 a 10 segundos y actualiza |
| `Address already in use` al ejecutar `minikube start` | El `control-panel` tomo la IP `192.168.49.2` | `docker compose stop control-panel`, luego `minikube start`, luego `docker compose start control-panel` |
| El HPA muestra `unknown` en CPU | Falta `metrics-server` | `minikube addons enable metrics-server` y espera 1 o 2 minutos |
| `deployment not found` o error al escalar | Los manifiestos no estan aplicados | `kubectl apply -f k8s/base/` |
| Las imagenes no arrancan o dan `ErrImageNeverPull` | Las imagenes no estan cargadas en minikube | Repite la seccion 4.5 |
| El modo vuelve a Compose solo | El panel se reinicio | Cambia el modo otra vez. Es normal |
| El puerto del API server cambia | Cambio el puerto al reiniciar minikube | Actualiza `K8S_API_SERVER` y recrea el panel |
