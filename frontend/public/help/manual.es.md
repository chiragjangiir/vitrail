# Manual de usuario de Vitrail

## Bienvenido a Vitrail

Vitrail es una plataforma de cartelería digital (digital signage): difunde contenidos (vídeos, imágenes, páginas web, canales de noticias, audio) en pantallas gestionadas por players, desde una interfaz web centralizada.

### Conceptos clave

- **Organización**: su espacio de trabajo. Contenidos, players y usuarios están aislados de las demás organizaciones.
- **Player**: el software instalado en el dispositivo conectado a una pantalla (NUC Linux, Raspberry Pi, PC Windows, box Android, Chromebox, BrightSign o una simple extensión de Chrome). Recibe sus instrucciones del servidor — nunca al revés — y sigue funcionando sin conexión.
- **Medio**: un contenido importado (vídeo, imagen, documento) o dinámico (página web, feed, entrada HDMI).
- **Playlist**: una secuencia de medios reproducida en bucle.
- **Programación (schedule)**: cuándo y en qué players se difunde una playlist.
- **Evento**: una difusión puntual o activada que tiene prioridad sobre la programación normal.
- **Campaña**: publicidad de anunciantes intercalada en sus bucles, vendida como cuota de voz (retail media).

### El recorrido típico

1. **Registrar un player**: genere un token de aprovisionamiento, instale el player y aparecerá en Players.
2. **Importar contenido** en la Mediateca.
3. **Crear una playlist** con ese contenido.
4. **Programar** la playlist en uno o varios players.

La pantalla muestra el contenido unos segundos después de guardar la programación.

> ¿Le falta un menú o una acción? Probablemente sea una cuestión de rol: pregunte a su administrador de organización (véase «Usuarios, roles y seguridad»).

## Players

### Registrar un player

Un player se une a su organización mediante un **token de aprovisionamiento**:

1. **Players → Provisioning** → **Nuevo token** (barra superior).
2. Elija el número máximo de players y una caducidad (o «Sin caducidad»).
3. Copie el token (`sfp_…`) y proporciónelo durante la instalación del player junto con la URL del servidor.

En el primer arranque, el player intercambia el token por su identidad permanente y aparece en **Players**. Un token activo puede **revocarse** (ya no registra; los players ya registrados siguen funcionando) y luego eliminarse.

### Aprovisionamiento por lotes y llave USB

El panel **Generar un payload** prepara la configuración de varias máquinas a la vez: ajustes por máquina o compartidos, importación CSV, resolución (Auto/HD/FHD/4K/8K/personalizada), Wi-Fi, reasociación de un player existente (lista con búsqueda). El payload se aplica por llave USB en los players Linux preparados, o por tarjeta SD en BrightSign.

### Supervisar y configurar a distancia

La lista de Players muestra el estado (en línea / desconectado / reposo programado) con la fecha del último contacto. El panel de un player muestra: máquina, pantalla, red, zona horaria, inventario de medios, captura de pantalla reciente, capacidades de descodificación.

Sin SSH, puede enviar: resolución, rotación, volumen, sonido, motor de renderizado, zona horaria, límite de ancho de banda. El botón **«Info en pantalla»** muestra un panel de diagnóstico directamente en la pantalla del player (nombre, red, programa en curso, medio reproducido). Botones puntuales: reiniciar la aplicación, reiniciar la máquina, forzar la resincronización, captura de pantalla. El botón **«Comandos masivos»** de la barra superior envía el mismo comando a todo un destino (organización, sitio, grupo de sitios, grupo de players); una vista previa enumera las pantallas afectadas **antes** del envío, y los comandos destructivos (reinicio, salir de la aplicación, mantenimiento) exigen una casilla de confirmación **y su PIN**.

Dos ajustes de «campañas» viven también en este panel: **Excluido de las campañas publicitarias** (opt-out) y el **tope de ocupación publicitaria** (véase Campañas).

### Grupos y sincronización LAN

Los **grupos de players** sirven como destino de difusión y soportan la **sincronización LAN**: varios players de la misma red local reproducen el mismo vídeo fotograma a fotograma (mural de pantallas). La sincronización es fiable cuando el grupo es **homogéneo** (mismo hardware) y los players comparten el mismo reloj (véase NTP). Un miembro del grupo puede designarse **relé NTP**.

### Extensión de Chrome (sin hardware)

La extensión de Chrome convierte un navegador en player: ideal para probar o para un puesto existente. Cargue la extensión (modo desarrollador), introduzca la URL del servidor y un token `sfp_…`. Límites: sin sincronización LAN, modo sin conexión reducido. Para un auténtico kiosco ChromeOS, use el player ChromeOS PWA.

## Sitios

Un **sitio** representa un lugar físico (tienda, sucursal). Cada player está vinculado a un sitio.

- **Zona horaria**: toda la programación se ejecuta en hora local del sitio. Un player vinculado se alinea automáticamente con la zona del sitio (aviso si difiere, corrección a distancia desde su panel).
- **Horario de apertura**: días y horas, con **excepciones con fecha** (festivo, inventario, velada) y cierre automático los **días festivos** (calendario regional opcional). Un día sin horario está cerrado. Estos horarios gobiernan el encendido de las pantallas (véase «Pantallas y alimentación») y el asistente los conoce («¿el sitio X abre el domingo?»).
- **Servidor NTP**: para que todos los players del sitio compartan exactamente el mismo reloj (imprescindible para la sincronización LAN).
- **Coordenadas**: sitúe el sitio en el mapa (usado por los informes geográficos y el portal del anunciante).
- **Categorías excluidas**: las categorías de industria vetadas de publicidad en este sitio (véase Campañas).
- La pestaña **Grupos de sitios** crea conjuntos (región, enseña) utilizables como destino en programaciones, eventos, campañas y actualizaciones.

Al pasar el cursor sobre un sitio (lista), una burbuja resume sus players y su ocupación publicitaria a 7 días.

## Mediateca

### Importar

**Mediateca → Importar**: vídeos, imágenes, documentos (PDF). La pestaña **Fotos libres** usa Unsplash/Pexels con atribución automática. Un vídeo se transcodifica automáticamente a un formato universal: el contenido anterior sigue difundiéndose durante el proceso, ninguna pantalla se queda en negro. Si la política de **renditions** de la organización está activa, un vídeo 4K genera también una versión Full HD — cada player recibe la resolución adecuada a su pantalla.

### Organizar

- **Carpetas** y subcarpetas (columna izquierda), movimiento masivo.
- **Etiquetas (tags)**: taxonomía por espacios de nombres (Mediateca → Tags), asignación múltiple y **filtrado por etiquetas a nivel de player** (un player solo reproduce los contenidos que coinciden con sus etiquetas).
- Búsqueda, filtro por tipo (imágenes/vídeos/audio/documentos/páginas web), paginación.

### Gestionar el ciclo de vida

- **Reemplazar el archivo** de un medio sin cambiar su identidad: las playlists que lo usan no se tocan, el cambio es atómico al final de la transcodificación.
- **Eliminar con seguridad**: la ventana de impacto lista playlists, programaciones, eventos y cestas que usan el medio, y su estado de difusión, antes de la eliminación en cascada.
- **Cuarentena**: bloquear un medio inmediatamente en todo el parque (incluso sin conexión), luego desbloquearlo o purgar su caché.
- **Conformidad**: cada vídeo lleva un veredicto (listo / difundible / no conforme) sobre su codificación, con reanálisis y modo passthrough (conservar el archivo original sin recodificar).

## Plantillas

Las **plantillas** definen composiciones multizona (vídeo principal + banda + logotipo…). El editor trabaja a la **resolución del lienzo** declarada (FHD, 4K, vertical, LED a medida) — elija la resolución de la pantalla destino. Una playlist asociada a una plantilla alimenta sus zonas; aparece un aviso si la resolución de la plantilla no coincide con la pantalla.

## Playlists

1. **Playlists → Nueva playlist**, luego añada medios (multiselección, búsqueda, carpetas).
2. Ajuste el orden, la duración de visualización de imágenes/documentos y la zona (plantillas multizona). Los **vídeos muestran su duración nativa** — se lee, no se ajusta.
3. Los cambios se acumulan como **borrador**: el botón **Publicar** los envía a los players de una vez (cambio limpio, nunca un estado vacío).

El encabezado del editor y cada miniatura de playlist muestran **el número de contenidos y la duración total** del bucle; el total sigue sus cambios en directo, borrador incluido.

### Previsualizar una playlist

El botón de **reproducción** — en la tarjeta de una playlist o en el editor — recorre el bucle como lo haría una pantalla. En una playlist asociada a una **plantilla multizona**, la vista previa compone todas las zonas a la vez, con la proporción de la plantilla, y cada zona avanza con su propio temporizador.

Es una vista previa, no el reflejo de una pantalla: cada zona empieza al principio de su bucle, y la rotación, los spots de campaña y el filtrado por etiquetas no se reproducen aquí. Los feeds, las páginas web y las entradas HDMI aparecen con su nombre en su sitio y su tamaño reales: se generan en la pantalla, en el momento de la difusión.

### Reglas de difusión por elemento

Cada elemento puede llevar su propia regla: días de la semana, franja horaria, rango de fechas de validez — en hora local del player. Las **excepciones por destino** lo afinan: tal player o grupo reproduce el elemento con una regla diferente. Un elemento sin regla es perpetuo.

### Playlist de rotación (N elementos por vuelta)

Una playlist puede **anidarse dentro de otra** como un elemento (botón **Añadir una playlist** en el editor). Su ajuste de **Rotación** decide el comportamiento:

- **Todos los elementos**: la sub-playlist se reproduce entera en cada vuelta.
- **N por vuelta — en orden**: N elemento(s) por vuelta, los siguientes en la vuelta siguiente (con 5 vídeos y 2 por vuelta: 1-2, luego 3-4, luego 5-1…).
- **N por vuelta — aleatorio**: orden mezclado, pero ningún elemento se repite hasta que todos hayan pasado; después se vuelve a mezclar.

Solo se permite un nivel de anidación; una playlist referenciada como sub-playlist no puede eliminarse (retírela antes de sus playlists padre). Las reglas y etiquetas por elemento viven en los elementos **de la sub-playlist**. La rotación permanece **sincronizada** entre pantallas de un grupo LAN, y la **simulación de línea de tiempo** muestra la secuencia real vuelta a vuelta. Si la misma sub-playlist aparece **varias veces** en una vuelta, todas sus apariciones reproducen el **mismo elemento en la misma vuelta** (sorteo compartido, garantía de determinismo) — para variar dentro de una vuelta, aumente «Elementos por vuelta».

Estos ajustes **siguen el borrador**, igual que los contenidos: al modificarlos aparece el aviso «Cambios sin publicar» y las pantallas siguen reproduciendo el bucle publicado hasta que pulse **Publicar** (o, en una playlist gobernada bajo moderación, hasta su **aprobación**).

## Cestas de audio

Las **cestas de audio** difunden un hilo musical en tienda, independiente del contenido visual: música de fondo, cuñas a intervalos o a hora fija, con **ducking** automático (la música baja durante una cuña). Cada player tiene un **rol de audio**: contenidos estándar (sonido de los vídeos), solo audio, o mixto (fondo sonoro + vídeos silenciados). El **panel de control de tienda** (LAN) permite al equipo actuar sin cuenta del CMS. Cada miniatura de cesta muestra **el número de pistas y la duración total**. Los informes de derechos musicales se apoyan en las reproducciones probadas.

## Programación

Una **programación** dice qué difundir (una playlist), dónde (players, grupos, sitios, grupos de sitios, etiquetas) y cuándo (días, franjas, rango de validez, prioridad).

1. **Programación** → cree una regla, elija playlist, destinos y ventana temporal.
2. Los players se actualizan en segundos.
3. El **calendario unificado** superpone programas visuales y de audio, eventos y campañas (leyenda con iconos). Filtre por tipo (pastillas Todo/Visuales/Audio/Eventos/Campañas) o por **destino** (grupo de sitios, sitio, player); la **exportación CSV** sigue los filtros activos. Si hay solapamiento, gana la **prioridad** más alta.

Las redes de varios niveles (sede, regiones, tiendas) componen su programación con la **Gobernanza jerárquica** — véase la sección dedicada más abajo.

## Gobernanza jerárquica (redes multisitio)

La **Gobernanza** sirve a las redes en las que varios niveles deciden lo que se muestra: una sede, regiones, tiendas. Cada nivel compone **su** parte de la programación, y las pantallas emiten la **suma** de los niveles de los que dependen. Una instalación de un solo sitio no la necesita: sin nodo, nada cambia (el campo «Nodo propietario» ni siquiera aparece).

### Las cinco nociones

- **El nodo** es un nivel de la organización. Es su **nivel** en el árbol (raíz = 0) el que fija el orden nacional → local, no su «tipo», que es solo una etiqueta.
- **El alcance** es el conjunto de pantallas que controla un nodo: se le vinculan pantallas, grupos de pantallas, sitios o grupos de sitios. El alcance de un nodo **incluye el de sus descendientes** — basta con vincular los sitios a los nodos de tienda.
- **La capa**: cada programa vinculado a un nodo produce una capa. Una pantalla compila todas las capas de los nodos de los que depende. Es lo que muestra la columna «Programa compilado», **para esa pantalla y en ese instante**.
- **La regla** dice cuánto puede tomar cada nivel. La más usada es «**contenidos por vuelta**»: con 1, cada nivel coloca un contenido por vuelta y **rota** sus contenidos.
- **El administrador de nodo** decide por ese nodo. ⚠️ Un permiso **nunca** basta: es esta asignación la que autoriza a escribir.

### Quién puede qué

El administrador de un nodo actúa sobre **su nodo y todo su subárbol**. Ve los niveles superiores **en solo lectura** y **no ve en absoluto** las ramas vecinas. Tres acciones suben siempre un escalón: **desvincular** un contenido de la gobernanza, **quitar la moderación** o **levantar una restricción**, y **validar** un envío — el validador debe administrar un nodo **padre**, y nadie valida su propio envío. Crear un nodo **raíz** está reservado al administrador de organización.

- **Gobernanza — Director**: construye la estructura — nodos, alcances, administradores, reglas. Lee el contenido, no lo produce.
- **Gobernanza — Programador**: crea los **programas** y las **listas** de sus nodos, envía a aprobación.
- **Gobernanza — Editor**: produce el contenido (listas, medios) y lo envía. No elimina ningún medio, no programa.
- **Gobernanza — Validador**: aprueba, rechaza o pide cambios en su subárbol.

Estos cuatro roles llevan una **semántica de alcance**: su titular solo actúa en su subárbol, y **el contenido no gobernado le es invisible**.

### El contenido gobernado

Una lista, un medio, una plantilla, un evento y una configuración VOD pueden pertenecer a un nodo (campo «Nodo propietario»). Sin nodo, el objeto pertenece a la organización y se comporta como antes. Un objeto vinculado solo lo pueden modificar los administradores de su nodo o de un nodo padre; si el nodo está marcado **«Contenido sujeto a aprobación»**, se **envía** en lugar de publicar, y es la validación la que publica. Esta moderación se **hereda hacia abajo**.

⚠️ **Dos malentendidos que salen caros.** Vincular una lista a un nodo decide **quién la edita**; no la **emite** — la emisión viene de un **programa** vinculado al mismo nodo. Y el **rol** dice lo que se puede hacer, la **asignación de administrador** dice **dónde**.

### Apuntar a una parte de las pantallas de un nodo

Por defecto, un programa vinculado a un nodo se emite en **todas** sus pantallas. Para apuntar solo a una parte, añádale **destinos**: **restringen** el alcance, nunca lo amplían, y un nivel inferior nunca puede restringir una capa **heredada**. Un destino que no retiene ninguna pantalla se rechaza nombrándolo, y se muestra el número de pantallas retenidas. **Dejar un programa sin destino suele ser lo correcto**: cubre entonces todo su nodo, incluidos los sitios añadidos más tarde.

### Ejemplo completo: entrada y salida de tienda

Objetivo: en cada tienda, la pantalla de **entrada** y la de **salida** emiten un contenido **de más** que las demás, y el responsable de la tienda cambia él mismo sus contenidos y sus programas.

**El árbol** — `Nacional` → `Dpt-01` → `Site-01`, `Site-02`.

**El alcance** — se vincula **el sitio** al nodo de tienda. El departamento y el nacional no tienen **ninguna asignación**: heredan del subárbol.

**Dos grupos de pantallas** — «Entradas» contiene la pantalla de entrada **de cada** tienda, «Salidas» las salidas. El grupo marca el **papel** de la pantalla, el nodo marca la **tienda**: el cruce de ambos designa la pantalla correcta, sin crear un grupo por tienda.

**Los contenidos** — cada tienda posee **sus propias** listas: local, entrada, salida. 🔑 Una lista compartida entre dos tiendas solo la puede modificar su propietario — el otro responsable ni siquiera puede leerla.

**Los programas** — uno por nodo, más dos por tienda:

- **Nacional** — programa «SC Nacional», **sin destino**: todas las pantallas de la red.
- **Dpt-01** — programa «SC Dpt», **sin destino**: todas las pantallas del departamento.
- **Site-01** — programa «SC Site-01», dirigido a las pantallas de la tienda: el contenido local.
- **Site-01** — programa «SC Entrada Site-01», dirigido al grupo «Entradas»: solo la entrada.
- **Site-01** — programa «SC Salida Site-01», dirigido al grupo «Salidas»: solo la salida.

Con «contenidos por vuelta = 1» en cada nodo, las pantallas ordinarias emiten **3 contenidos por vuelta** (nacional + departamento + local) y tanto la entrada como la salida emiten **4**.

**Añadir una tienda** son entonces cinco gestos: crear el nodo bajo el departamento, vincularle el sitio, crear sus tres listas, crear sus tres programas, añadir su pantalla de entrada al grupo «Entradas» y la de salida al grupo «Salidas». Los programas nacional y de departamento no se tocan.

### Componer un alcance a escala

El botón **«Añadir pantallas»** abre una búsqueda **del lado del servidor**: filtre por naturaleza (pantalla, grupo de pantallas, sitio, grupo de sitios), seleccione **varios destinos a la vez**, y cada línea indica **cuántas pantallas representa**. Una pantalla aún vinculada a **ningún** nodo se propone y se **etiqueta**: así un olvido de instalación se ve y se repara.

### Reorganizar y diagnosticar

Un nodo puede **moverse** bajo otro padre: rutas, niveles y emisión de todo su subárbol le siguen. No puede moverse bajo uno de sus propios descendientes, ni a una rama que no se administra.

Cuando la vista previa de una pantalla está vacía, el mensaje **nombra la causa**: sin nodo, sin programa en el nodo, programa inactivo, sin lista, **sin regla horaria** (nunca estará activo), o fuera de su ventana en ese instante.

## Eventos

Un **evento** tiene prioridad temporal sobre la programación: promoción, anuncio, contenido activado.

- Contenido: una playlist o un solo medio. Destino: organización, sitio, grupo o player — y los tipos se pueden **mezclar** en un mismo evento («este sitio» + «estas 3 pantallas», como las campañas): las selecciones se acumulan y el resumen nombra todo lo incluido. «Toda la organización» reemplaza las demás selecciones.
- Tipos: **manual** (activado a demanda), **programado** (ventana fecha/hora, opcionalmente recurrente).
- **Cuña horaria**: en un evento programado en «Reproducir una vez», active la repetición a intervalo fijo (p. ej. una cuña cada 30 minutos). El campo solo aparece en esa combinación.
- **Zona horaria de referencia** (evento programado): define qué significa «18:00». Por defecto, la del servidor. En una red repartida por varios países, elíjala explícitamente — un evento se activa en **un único instante**, no a las 18:00 en cada país. La zona se recuerda junto al horario en la lista.
- ⚠️ No confundir con el **embargo**, que es un instante **absoluto** (UTC): no depende de ninguna zona horaria y este ajuste no lo afecta.
- Opción **«mantener las pantallas encendidas»**: mantiene la visualización durante el evento incluso fuera del horario de apertura.
- Al terminar, el player vuelve exactamente a su programación (hora actual).
- Un evento **(re)activado en plena ventana** con un medio nunca distribuido puede tardar unos minutos en aparecer (el player descarga primero el archivo — nunca una pantalla negra). Actívelo/prográmelo con antelación para un cambio instantáneo.

## Difusión a demanda (VOD)

La página **On-Demand** difunde un contenido inmediatamente, por encima de la programación, sin tocar las playlists. Una **config VOD** agrupa medios y un destino: **players seleccionados** (del mismo sitio) o un **sitio completo** — en cuyo caso cualquier player añadido después al sitio se incluye automáticamente; los medios se pre-descargan, la activación es instantánea: **Una vez** o **En bucle** (hasta Stop). El permiso `vod : trigger` basta para una cuenta «tienda». Al final, la programación se reanuda a la hora actual.

> Particularidades **BrightSign**: el arranque y la parada pueden tardar **hasta 2 segundos** (relé local integrado) — es normal. Durante la difusión, la playlist queda suspendida (un solo flujo de vídeo por hardware en estos players) y luego se reanuda a la hora actual. La pre-descarga inicial puede tardar con archivos 4K: mientras un medio no esté en caché, se reproduce en streaming (arranque diferido).

## Entrada HDMI

El medio **«Entrada HDMI»** muestra cualquier fuente conectada a la entrada HDMI del player (decodificador de TV, box, consola) — reproducción puramente local. Compatible: BrightSign con entrada HDMI física (gamas XT, 4K114x, XD1230).

- **En playlist**: una franja conmuta a la fuente y luego reanuda la playlist; los players sin entrada ignoran el elemento. Sin señal, la pantalla muestra «No Signal Detected» (nunca una pantalla negra).
- **A demanda**: mediante una config VOD, botones **Conmutar a HDMI / Volver a la playlist** (reanudación a la hora actual).
- **Página local**: cada BrightSign compatible sirve `http://<ip>:8888/control` — conmutar/volver desde cualquier teléfono de la tienda, sin cuenta ni servidor (activación + PIN por player).
- Salvaguardas: una conmutación activa se termina al apagarse la pantalla; cada sesión queda trazada (auditoría + prueba de reproducción firmada con la duración real).

## Feeds y páginas web

### Feeds (canales de noticias)

Un **feed** es una fuente consultada por el servidor: RSS/Atom, Google News, YouTube, meteo, cripto, finanzas, redes sociales (vía el proxy de feeds). Modos de visualización: cinta deslizante, carrusel, cuadrícula, artículo a pantalla completa, composición dividida, lista, muro social, gráfico. Opciones: **resumen IA** de los artículos (una frase legible de lejos), **moderación** (validar cada artículo antes de difundir), miniaturas en caché en el player (funciona sin conexión).

### Páginas web (URL Display)

Muestre una página web en pantalla: modo **WebView** (renderizado en directo en el player) o **captura de servidor** (el servidor fotografía la página periódicamente — para páginas que rechazan la integración o requieren autenticación del lado servidor). Una página web es un medio como cualquier otro: etiquetas, playlists, programación.

## Generación con IA

Vitrail genera imágenes, vídeos, música y voces en off a partir de una descripción. El medio generado entra en la mediateca normalmente.

- **Requisito**: las claves de IA de su organización (**Configuración → Claves IA**) — fal.ai (imágenes/vídeos/música/voz), ElevenLabs (audio pro), Anthropic (asistente de redacción y Studio). Usted paga a su propio proveedor; sin clave, la función está inactiva.
- **Dónde**: Mediateca → **Generar (IA)** para un recurso; **Studio** para una campaña completa a partir de un brief (conceptos por formato, coste total mostrado antes de generar).
- **Prompts**: los modelos trabajan en inglés — el **asistente de redacción** convierte su idea (en cualquier idioma) en un prompt inglés optimizado + prompt negativo. Sea simple: sujeto + acción + estilo; para vídeo añada cámara y luz; nunca meta-instrucciones («contenido promocional…» acaba dibujado en la imagen).
- **Edición**: recorte de fondo, retoque por instrucción, variaciones múltiples, imagen → vídeo (describa solo el movimiento).
- Se muestra una **estimación de coste** antes de cada generación.

## Generador promo

El **Generador promo** crea un cartel promocional (imagen o vídeo corto) a partir de un producto, un precio y un diseño. El resultado va a la mediateca y se difunde como cualquier otro medio.

- **Dónde**: Mediateca → **Generador promo**.
- **Un recorrido en seis pasos**: **¿Para quién?** · **El producto** · **Texto y precio** · **Diseño** · **El fondo** · **Retoques libres**. Solo hay un paso abierto a la vez, para que todos sus campos quepan en pantalla; plegado, un paso **muestra su valor**. Se abren en cualquier orden.
- **«¿Para quién?» primero**: mi enseña o un anunciante — la **carta gráfica se deduce** (colores, fuente, logotipo, menciones) en lugar de elegirse.
- **Partir de una URL de producto**: pegue la dirección de una ficha y se extraen el nombre, el precio y la foto. Todo sigue siendo modificable: es una ayuda a la escritura, no una fuente de verdad.
- **El precio es obligatorio.** **Generar** permanece apagado mientras falte, y el aviso bajo la vista previa dice qué falta **y lleva al paso correspondiente**. El mismo aviso señala los problemas de legibilidad, revisados por el servidor antes de producir.
- **La IA solo hace el fondo** (y recorta el producto). Precio, descuento, nombre y menciones legales los coloca el compositing a partir de lo que usted escribió, así que son exactos.
- **Encadenar**: «Rehacer con otro producto» conserva marca, diseño, fondo y menciones; los **preajustes** recuperan una configuración completa.

### Modo serie — un diseño, N productos

El conmutador **Un visual / Serie**, arriba, sustituye la vista previa por una **tabla**: una fila por visual. El recorrido de la izquierda sigue definiendo lo **común** (marca, diseño, fondo, menciones, moneda); la tabla solo lleva lo que **varía** — producto, eslogan, precio, precio tachado, descuento.

- **Tres formas de rellenarla, acumulables**: añadir una fila a mano, **importar un CSV** o **pegar desde una hoja de cálculo** (Excel, Google Sheets). Los encabezados se reconocen en español, francés e inglés, en cualquier orden. ⚠️ Sin encabezado reconocido, las columnas se leen **en orden** y la pantalla lo indica — revise la tabla.
- **La importación añade**, no reemplaza: puede importar dos archivos o completar a mano.
- **Una fila sin precio no detiene la serie**: se resalta, se nombra en el aviso y se omite. El botón indica cuántos visuales se lanzarán realmente.
- Cada visual se **nombra según su producto**, de lo contrario todos llegarían con el mismo nombre a la mediateca.

## Manuales de marca

Un **manual de marca** declara de una vez los colores, la fuente, el logotipo, las menciones legales y el tono de una marca. El **Generador promo** lo usa después para rellenar cada visual.

- **Dos alcances**: un manual para su **organización** y uno por **anunciante**. Cuando un visual se hace para un anunciante, se aplica el suyo; si no, el de la organización.
- **Dónde**: Generador promo → botón **Cartas gráficas y fuentes** en la barra superior. Reservado al administrador de la organización.
- **Un manual solo reemplaza lo que declara**: un color sin marcar significa «el manual no dice nada», y la plantilla conserva el suyo. Eso permite imponer un único color de acento sin borrar los demás.
- **Rellena, no bloquea**: en un visual concreto, lo que usted escribe prevalece sobre el manual. Las menciones legales se copian una sola vez: si las borra a propósito, no vuelven.
- **El logotipo y el nombre nunca los dibuja la IA**: un fondo generado solo recibe la paleta y el tono, como atmósfera a buscar. Logotipo, nombre y menciones se colocan después mediante el compositing, por lo que son exactos. El botón «Colocar el logotipo de la marca» lo añade como capa movible.
- Mientras no exista ningún manual, nada cambia: los visuales conservan los colores de su plantilla.

## Campañas (retail media)

La página **Campañas** vende sus pantallas como inventario publicitario: un anunciante compra una **cuota de voz (SOV)** — un porcentaje del tiempo de antena — sobre un periodo y unas pantallas.

### Anunciantes y exclusión competitiva

Cree sus **anunciantes** (página Anunciantes): cada uno recibe una carpeta «Anunciantes/<nombre>» y una o varias **categorías de industria**. En cada **sitio**, liste las categorías **excluidas**: los anunciantes afectados no pueden ni segmentar ni difundir en ese sitio (aplicado en segmentación, ocupación, presupuesto, informe, portal y difusión).

### Crear y publicar una campaña

Una campaña = periodo (+ ventana horaria diaria opcional), **SOV vendida en %**, precio (por SOV o tanto alzado, introducido manualmente — se calcula un **presupuesto indicativo** según las tarifas por pantalla), destinos (acumulables: org, sitios, grupos de sitios, grupos, players) y creatividades (vídeos/imágenes, rotación ponderada). Estados: borrador → publicada (programada / en directo / terminada), pausa (retirada inmediata), reanudación, anulación.

- **Inventario**: la proyección de ocupación avisa al 80 % y bloquea al 100 % del **tope** de cada pantalla (tope ajustable por player o sitio — p. ej. pantalla de caja limitada al 20 %); un org-admin puede forzar (sobreventa asumida).
- **Tarifas**: € por 1 % de SOV al día, heredadas org → sitio → player.
- **SOV alcanzable**: un aviso ámbar señala cuándo la SOV pedida supera lo que el bucle realmente programado permite, con un botón «Usar X %».
- **Duración máxima de creatividades**: ajustable por org (por defecto 30 s) — rechazo al añadir y re-verificación al publicar.
- **Aprobación de creatividades** (opcional, por org): toda creatividad nueva nace «Pendiente» y debe aprobarse antes de difundirse.
- **Calendario**: Gantt mensual de campañas con carga por día (ámbar/rojo).
- **Importación**: campaña completa desde un JSON (vista previa dry-run, creación en borrador, publicación manual), también **por API** con una clave `sfi_`.

### Difusión, prueba e informe

Las creatividades se **intercalan en el bucle existente** a la frecuencia de la SOV vendida — nunca dos anuncios seguidos (como máximo un anuncio por vuelta de bucle; el exceso se convierte en subservicio medido y alertado). Cada pase emite una **prueba de reproducción firmada** por la pantalla. El **informe del anunciante** da pases, tiempo de antena, SOV servida vs vendida, desglose jerárquico grupos → sitios → pantallas, importe — exportación **PDF marca blanca** y **enlace público protegido** (contraseña, lista blanca de IP). Notificaciones: campaña iniciada / terminada / **subservida**.

## Portal del anunciante

El **portal** (`/portal`) es el espacio marca blanca de sus anunciantes: cada uno solo ve **sus** campañas.

- **Abrir un acceso**: panel del anunciante → sección Acceso al portal → invitar por email (contraseña inicial mostrada una sola vez). Una cuenta de anunciante siempre aterriza en el portal, nunca en el CMS.
- **El anunciante puede**: seguir sus campañas e informes (PDF), **crear una campaña** (sitios en el mapa — los incompatibles con su categoría aparecen en gris —, periodo, SOV o **Exclusivo** = 100 %, disponibilidad agregada ok/ajustado/completo y **presupuesto en directo**), subir sus creatividades (cuotas ajustables, por defecto 20 archivos / 1024 MB — siempre revisadas antes de difundir), **enviar a validación**, corregir y reenviar si se piden cambios, guardar **listas de sitios**, elegir su **idioma** (5 disponibles).
- Si la organización activa la **«Selección por pantalla (portal)»**, el anunciante puede marcar pantallas concretas dentro de cada sitio.
- Una **campana** le informa de las decisiones (más un email si usted lo marca al decidir).

## Aprobaciones (validaciones)

La página **Aprobaciones** centraliza las solicitudes de aprobación — actualmente las campañas (enviadas desde el CMS o el portal).

1. **Enviar**: «Enviar a aprobación» (una sola solicitud activa por recurso). Una campaña en revisión no puede publicarse.
2. **Revisión**: el validador lo ve todo — creatividades reproducibles, anunciante, periodo, SOV pedida y alcanzable, presupuesto, destinos con nombre, ocupación proyectada con el detalle de las campañas ya en curso.
3. **Decisión**: aprobar / rechazar / pedir cambios (motivo obligatorio), con opción de **email al anunciante** (marcada por defecto). La aprobación aprueba también las creatividades pendientes de la solicitud.
4. **Reenvío** tras las correcciones; historial conservado.

Los validadores (permisos `approvals`) ven la cola de toda la organización y una **campana** en la barra superior; exportaciones **CSV/PDF** de la cola; las solicitudes en estado terminal pueden retirarse de la lista (traza conservada en auditoría).

## Informes y analítica

- **Executive Dashboard**: KPI de la red, **Network Health Score**, tendencias — filtros por sitio/grupo, exportación **PDF marca blanca** (su logotipo), envío **programado por email**.
- Cuadros especializados: NOC (salud del parque), contenido, geo (mapa de sitios), audiencia.
- **Proof of Play**: cada reproducción se registra, se encadena (Merkle) y se **firma por el player** — verificación de integridad y **certificado** exportable. Los informes de derechos musicales se apoyan en ello.
- **Enlaces de compartición**: publique un informe de solo lectura protegido (contraseña, lista blanca de IP) para un cliente o la dirección.
- **Conectores BI**: tres flujos CSV (clave API `sfr_`) para Power BI, Tableau, Excel, Metabase.

## Notificaciones

**Configuración → Notificaciones**: **canales** (webhook JSON o **email**, hasta 20 destinatarios) y **reglas** que les asocian eventos: player desconectado (el reposo programado no suena; un parque no despierto tras la apertura, sí), feed en error, despliegue OTA fallido, campañas (iniciada/terminada/subservida), validaciones (enviada/aprobada/rechazada/cambios). Botón de envío de prueba en cada canal.

## Asistente IA y Jeanine

El **asistente** (botón inferior derecho o **Ctrl+Shift+A**) conoce su cuenta y esta documentación, y responde en su idioma.

- **Lectura**: players (estado, por qué una pantalla está apagada), playlists («quién la reproduce»), sitios y **horarios de apertura**, programaciones, medios (tiempo de antena probado, nunca reproducidos), campañas (estado, informe), sesiones HDMI, alertas.
- **Acciones**: **prepara** (nunca ejecuta solo) — añadir/quitar medios de una playlist, crear playlist/feed/evento/programación, reiniciar players, captura, pantalla on/off, conmutación HDMI, VOD, zona horaria, ordenar medios en carpetas, **actualización OTA de los players** (última versión estable). Usted confirma con un botón; las acciones sensibles son solo para org-admin.
- **Jeanine (Telegram)**: el mismo asistente por mensajería. Vincule su cuenta desde **Perfil → tarjeta Mensajería** (`/link CÓDIGO` al bot); el org-admin gestiona las cuentas vinculadas en Configuración → Mensajería. Las acciones sensibles (reinicio, apagado de pantalla, borrado de programación, OTA…) exigen su **código PIN de 6 dígitos** (definido en el perfil; una acción, 2 minutos, bloqueo tras 3 errores, mensaje borrado del hilo — nunca por voz).
- **Voz**: envíe un mensaje de voz (≤ 2 min) — transcripción en el idioma de su perfil, respuesta en texto + nota de voz (se requieren claves fal.ai y ElevenLabs).
- Costes: el asistente usa **las claves IA de su organización** y respeta su cuota.

## Actualizaciones de players (OTA)

**Configuración → Actualizaciones** dirige las actualizaciones a distancia de todos los tipos de players. **Ninguna actualización automática sin su aprobación.**

- **Inventario**: versión actual vs última disponible **por plataforma**, filtros combinados (SO, versión, estado, sitio, grupo).
- **Catálogo**: sus versiones publicadas (SemVer, canal, plataforma).
- **Importar una versión** (Linux/RPi/Windows/Android): por **URL** o por **archivo** (.tar.gz/.apk) — plataforma y versión **detectadas automáticamente**, con vista previa antes de confirmar; el archivo se almacena en su servidor, los players lo descargan desde allí.
- **Versiones servidas** (BrightSign/ChromeOS): estos players obtienen su código **con la actualización del servidor**; **declare** la versión servida para poder desplegarla. **Fijación**: actualizar el servidor **no** avanza un player hasta que despliegue la versión — ideal para probar en un entorno de pruebas antes que la flota.
- **Flujo recomendado**: publicar en **Beta** (invisible para el parque) → desplegar a un grupo de prueba → **Pasar a estable** → desplegar ampliamente.
- **Despliegue**: versión + destinos (player, grupo, sitio, etiquetas, org) + estrategia (inmediata, gradual, programada) + **ventanas horarias** (descarga / instalación en hora local — sin reinicios a media jornada). Seguimiento por player (descarga → listo → instalación → éxito/fallo), anillo de progreso, pausa/reanudación/anulación. Un player desconectado aplica a su regreso.
- **Por el asistente**: «actualiza los players» propone la última estable de cada plataforma a los players atrasados (org-admin; PIN por Telegram).

## Pantallas y alimentación

Vitrail enciende y apaga sus pantallas según el **horario de apertura del sitio** — el player permanece encendido, solo se gobierna la pantalla.

1. Rellene los horarios del sitio (con excepciones y festivos) y active el **auto-power** (márgenes opcionales antes/después).
2. En cada player: **Seguir los horarios del sitio** (recomendado), ventana personalizada, siempre encendido, o manual.
3. Método según el equipamiento: controlador **RS232/IP** (pantallas profesionales), **HDMI-CEC**, o el repliegue **corte de la salida de vídeo** (la pantalla pasa a reposo).

Cada player conoce sus ventanas de encendido **con 14 días de antelación**: si el servidor es inalcanzable, gobierna su pantalla por sí solo. Un player apagado por el programa se marca **«Reposo programado»** — sin alerta; si no ha vuelto tras la apertura, salta una alerta. Los botones Encender/Apagar del panel son puntuales; un evento puede «mantener las pantallas encendidas».

## Servidor y duración de las codificaciones

Cada vídeo importado se **vuelve a codificar** para que todas las pantallas puedan reproducirlo: es la tarea más pesada del servidor. La página **Configuración → Servidor** explica por qué tarda lo que tarda.

**Capacidad de codificación** — la línea que lo explica casi todo: **aceleración por hardware activa** o no. Sin tarjeta gráfica utilizable, la codificación va por el procesador y es mucho más lenta. **Velocidades medidas** = las observadas realmente en sus propios archivos. **Disco de trabajo** = espacio libre donde el worker escribe sus archivos temporales.

> **«Ningún worker multimedia responde»** no es un detalle visual: ninguna codificación puede completarse. Esta información viene del **worker**, no del servidor web — cuando calla, la página lo dice en lugar de mostrar valores obsoletos.

**Antes de lanzar una codificación, el servidor mide**: codifica unos diez segundos de **su** archivo con el comando exacto que se usará y extrapola. Tres casos: **menos de 20 min**, arranca solo · **de 20 min a 4 h**, decide usted y el medio espera en **Decisión requerida** · **más de 4 h**, se rechaza por defecto, salvo que un administrador lo fuerce. El rechazo no es un callejón sin salida: la pantalla propone codificar en **definición inferior**, cada una con su propia estimación.

Esta página está reservada al **titular de la licencia**. Si su servidor lo administra un proveedor, la pantalla se lo indica: la capacidad y la cola dependen de su explotación.

## Usuarios, roles y seguridad

**Roles incluidos** — esta lista solo enumera los derechos que el servidor aplica realmente:

- **Administrador de organización**: todo, dentro de su organización.
- **Diseñador**: medios y plantillas (crear/editar/eliminar), playlists (crear/editar).
- **Programador**: programación, eventos y VOD (crear/editar/activar); lectura de players, playlists, medios.
- **Responsable de campañas**: campañas de principio a fin (crear, publicar, informes); lectura de medios, plantillas, informes.
- **Aprobador**: revisar, aprobar o rechazar solicitudes; lectura de medios, playlists, plantillas.
- **Lector de informes**: solo consulta de informes.
- **Operador de tienda**: controlar las cestas de audio de su tienda.
- **Gestor de gobernanza**: configurar la jerarquía de gobernanza (nodos, delegaciones); lectura de contenidos.
- **Editor de gobernanza**: componer el contenido de su nodo (listas, medios, flujos) y enviarlo a aprobación; **no elimina medios**.
- **Validador de gobernanza**: decidir sobre las solicitudes de aprobación de su alcance; **nunca su propio envío**, y solo desde un nodo superior.
- **Programador de sitio**: programar la difusión de los **nodos que administra** (su alcance viene de su asignación de nodo, no del permiso solo).
- **Observador**: solo lectura en todo.
- **Anunciante (portal)**: sus propias campañas e informes, desde el portal.

> **Los menús se adaptan al rol**: lo que un usuario no puede usar queda oculto. Un menú desaparecido significa un permiso de lectura ausente, no una avería.

> Los roles **Usuario API** y **Player** no otorgan nada y ya no se ofrecen: las integraciones usan **claves API** y los players un **token de máquina**.

> **Rol personalizado**: créelo y luego **haga clic en su fila** para marcar sus permisos. Los roles de sistema son de solo lectura; los permisos en gris (próximamente) corresponden a funciones aún no desarrolladas.

- **Configuración → Usuarios y Roles**: usuarios, **grupos** (los roles del grupo se suman a los de la cuenta; ámbito org/sitio/grupo de players) y **roles personalizados** compuestos de permisos atómicos `módulo : operación` (véase la lista anterior).
- La eliminación de un usuario es una **desactivación** (el email queda reservado); eliminar una cuenta de anunciante la desvincula del portal.
- **2FA (TOTP)**: activable por usuario, obligatoria para los administradores.
- **Claves API**: exportaciones BI (`sfr_`), importación de campañas (`sfi_`) — valor mostrado una sola vez, revocables.
- **Configuración → Seguridad**: política de sesión, intentos de conexión.
- Toda acción sensible queda trazada en el **registro de auditoría**.

## Perfil y preferencias

**Configuración → Perfil**: nombre, email, contraseña, **idioma de la interfaz** (francés, inglés, español, portugués, alemán — el asistente y los emails lo siguen), tema claro/oscuro (botón en la barra superior), 2FA, **tarjeta Mensajería — Telegram** (vínculo Jeanine + **código PIN** de acciones sensibles), reactivación de las burbujas de ayuda.

## Solución rápida de problemas

- **Player desconectado**: compruebe alimentación, red, URL del servidor. Fuera del horario de apertura, «Reposo programado» es normal (el auto-power apagó la pantalla; algunas boxes cortan también su red).
- **«No Signal Detected»**: la fuente HDMI conectada no emite (apagada, desenchufada) — la imagen vuelve sola al volver la señal.
- **«Medio no disponible»**: player no actualizado para ese tipo de contenido, o transcodificación del servidor sin terminar.
- **Pantalla negra/congelada**: verifique la transcodificación; en un mural sincronizado, mantenga el grupo homogéneo; «Info en pantalla» muestra el diagnóstico in situ.
- **Sin sonido**: verifique el rol de audio del player (estándar / solo audio / mixto), el volumen enviado y el silencio.
- **El contenido no cambia**: ¿player en línea? ¿La programación apunta realmente a ese player/grupo? Todo cambio envía normalmente una sincronización inmediata.
- **Sin conexión**: los players nativos reproducen su contenido localmente (playlists, vídeos, feeds en caché) incluso con el servidor caído; la extensión de Chrome depende más de la red.

> ¿Necesita más? Pregunte al asistente (Ctrl+Shift+A) — conoce este manual y el estado de su cuenta.
