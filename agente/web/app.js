"use strict";
// Página del agente. Lee los archivos EN EL NAVEGADOR y los envía como JSON a /v1/revisiones.
// Todo el texto que viene del código revisado o del modelo se inserta con textContent (función h): nunca como HTML.

const SALTAR = new Set(["node_modules", "bin", "obj", ".git", ".venv", "dist", ".vs", ".idea", "packages"]);
const MOVILES = new Set(["androidmanifest.xml", "network_security_config.xml", "info.plist"]);
const ETIQUETA_LENG = { csharp: "C#", typescript: "TS", javascript: "JS", html: "HTML", tsql: "SQL", xaml: "XAML",
  config: "Config", razor: "Razor", xml: "XML", yaml: "YAML", kotlin: "Kotlin", swift: "Swift" };
const VEREDICTO = {
  NO_APTO: ["No apto para pase a producción", "Hay incumplimientos obligatorios detectados con certeza."],
  REVISAR: ["Requiere revisión humana", "Quedan casos de confianza media o derivados a una persona."],
  APTO: ["Apto", "No quedan incumplimientos detectados."],
};
const AYUDA_TIPO = { web: "Una aplicación web incluye las reglas de su API.", api: "Reglas de EST-API-001 y EST-SEG-001.",
  escritorio: "Reglas de EST-DSK-001 para WPF y WinForms.", movil: "Reglas del capítulo 11 de EST-SEG-001." };
const AYUDA_BD = { nueva: "Nomenclatura de EST-WEB-001 (esquemas, PascalCase).",
  legada: "Nomenclatura de EST-DSK-001: los objetos existentes no se renombran." };
const $ = (id) => document.getElementById(id);

const estado = {
  info: { extensiones: [], lenguajes: [], familias: [], max_archivos: 50, max_bytes_archivo: 200000 },
  archivos: [],          // {nombre, contenido, bytes, lenguaje, nota}
  ignorados: [],         // {nombre, motivo}
  revision: null,        // respuesta de /v1/revisiones
  final: null,           // respuesta de la aprobación
  aprobados: new Set(),  // "archivo\u0000P001"
  actual: null,          // archivo abierto en la mesa
  filtro: "todos",
};

// ---------------------------------------------------------------- utilidades
function h(tag, attrs = {}, ...hijos) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (v !== false && v != null) e.setAttribute(k, v === true ? "" : v);
  }
  for (const x of hijos.flat(Infinity)) if (x != null && x !== false) e.append(x instanceof Node ? x : String(x));
  return e;
}
const chip = (texto, clase = "") => h("span", { class: `chip ${clase}` }, texto);
const kb = (n) => (n < 1024 ? `${n} B` : `${(n / 1024).toFixed(n < 10240 ? 1 : 0)} KB`);
const clave = (archivo, parche) => archivo + "\u0000" + parche;
const extension = (nombre) => { const i = nombre.lastIndexOf("."); return i < 0 ? "" : nombre.slice(i).toLowerCase(); };
const base = (ruta) => ruta.split("/").pop();
const plural = (n, uno, varios) => `${n} ${n === 1 ? uno : varios}`;

function lenguajeDe(nombre) {
  if (nombre.toLowerCase().endsWith(".xaml.cs")) return "csharp";
  const ext = extension(nombre);
  return estado.info.lenguajes.find((l) => l.extensiones.includes(ext))?.lenguaje || null;
}
function esMovil(nombre, lenguaje) {
  const b = base(nombre).toLowerCase();
  return lenguaje === "kotlin" || lenguaje === "swift" || MOVILES.has(b) || b.endsWith(".plist");
}

async function api(ruta, cuerpo) {
  let r;
  try {
    r = await fetch(ruta, cuerpo === undefined ? {} : {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(cuerpo) });
  } catch {
    throw { title: "No hay conexión con la API", detail: "Comprueba que uvicorn sigue en marcha en la terminal y vuelve a intentarlo." };
  }
  const datos = await r.json().catch(() => ({ title: `Error ${r.status}`, detail: "La respuesta no es JSON. Revisa la terminal de uvicorn." }));
  if (!r.ok) throw datos;   // Problem Details (RFC 9457)
  return datos;
}

function avisar(e, tipo = "mal") {
  const p = e && e.title ? e : { title: "Algo falló", detail: String(e) };
  const extra = p.errors ? Object.entries(p.errors).map(([k, v]) => `${k}: ${v}`) : (p.desconocidos || []);
  const caja = h("div", { class: `aviso ${tipo}`, role: "alert" }, h("b", {}, p.title), p.detail ? h("span", {}, p.detail) : null,
    extra.length ? h("ul", {}, extra.map((x) => h("li", {}, x))) : null);
  $("avisos").append(caja);
  setTimeout(() => caja.remove(), 9000);
}

function descargar(nombre, texto, tipo = "text/plain") {
  const url = URL.createObjectURL(new Blob([texto], { type: `${tipo};charset=utf-8` }));
  const a = h("a", { href: url, download: nombre });
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

function enlaceRegla(id) {
  return h("a", { class: "regla", href: "#", title: `Ver el texto de ${id}`, onclick: (ev) => { ev.preventDefault(); verRegla(id); } }, id);
}

function marcarPaso(n) {
  [1, 2, 3].forEach((i) => {
    const li = $(`paso${i}`);
    li.classList.toggle("activo", i === n); li.classList.toggle("hecho", i < n);
    i === n ? li.setAttribute("aria-current", "step") : li.removeAttribute("aria-current");
  });
}

// ---------------------------------------------------------------- 0. qué acepta el servidor
async function cargarInfo() {
  try {
    estado.info = await api("/v1/info");
    $("estado").replaceChildren(h("b", {}, estado.info.reglas), " reglas, modelo ", h("span", { class: "modelo" }, estado.info.modelo));
    $("limites").textContent = `Hasta ${estado.info.max_archivos} archivos de ${kb(estado.info.max_bytes_archivo)} cada uno.`;
    $("inArchivos").setAttribute("accept", estado.info.extensiones.join(","));
    $("familias").replaceChildren(...estado.info.familias.map((f) => h("div", {},
      h("dt", {}, f.nombre, h("small", {}, f.detalle)), h("dd", {}, f.extensiones.map((e) => h("span", { class: "ext" }, e))))));
  } catch (e) {
    $("estado").textContent = "Sin conexión con la API";
    avisar(e);
  }
}

// ---------------------------------------------------------------- 1. adjuntar
// Archivos de Windows: UTF-8 (con o sin BOM), UTF-16 (Bloc de notas, PowerShell) o ANSI/cp1252 con tildes.
async function leerTexto(file) {
  const b = new Uint8Array(await file.arrayBuffer());
  if (b[0] === 0xff && b[1] === 0xfe) return { texto: new TextDecoder("utf-16le").decode(b.subarray(2)), nota: "UTF-16" };
  if (b[0] === 0xfe && b[1] === 0xff) return { texto: new TextDecoder("utf-16be").decode(b.subarray(2)), nota: "UTF-16" };
  if (b.subarray(0, 8000).includes(0)) throw new Error("es un archivo binario");
  try {
    return { texto: new TextDecoder("utf-8", { fatal: true }).decode(b), nota: "" };
  } catch {
    return { texto: new TextDecoder("windows-1252").decode(b), nota: "convertido desde ANSI" };
  }
}

async function agregar(lista) {   // lista de {file, ruta}
  const antes = estado.archivos.length;
  let reemplazados = 0;
  for (const { file, ruta } of lista) {
    const nombre = (ruta || file.name).replace(/\\/g, "/");
    if (nombre.split("/").some((p) => SALTAR.has(p))) continue;
    const lenguaje = lenguajeDe(nombre);
    if (!lenguaje) { estado.ignorados.push({ nombre, motivo: `la extensión ${extension(nombre) || "(sin extensión)"} no está en los estándares` }); continue; }
    if (file.size > estado.info.max_bytes_archivo) { estado.ignorados.push({ nombre, motivo: `pesa ${kb(file.size)}; el máximo es ${kb(estado.info.max_bytes_archivo)}` }); continue; }
    let leido;
    try { leido = await leerTexto(file); } catch (e) { estado.ignorados.push({ nombre, motivo: e.message }); continue; }
    const previo = estado.archivos.findIndex((a) => a.nombre === nombre);
    const entrada = { nombre, contenido: leido.texto, bytes: file.size, lenguaje, nota: leido.nota };
    if (previo >= 0) { estado.archivos[previo] = entrada; reemplazados++; continue; }
    if (estado.archivos.length >= estado.info.max_archivos) { estado.ignorados.push({ nombre, motivo: `ya hay ${estado.info.max_archivos} archivos en la lista` }); continue; }
    estado.archivos.push(entrada);
  }
  pintarSeleccion();
  const nuevos = estado.archivos.length - antes;
  if (!nuevos && !reemplazados && lista.length) avisar({ title: "Ningún archivo agregado", detail: "Mira el motivo de cada uno debajo de la lista." }, "adv");
}

async function leerEntrada(entrada, ruta = "") {   // carpetas arrastradas
  if (entrada.isFile) return [{ file: await new Promise((ok, mal) => entrada.file(ok, mal)), ruta: ruta + entrada.name }];
  if (SALTAR.has(entrada.name)) return [];
  const lector = entrada.createReader(), todas = [];
  for (;;) {   // readEntries entrega los archivos por lotes
    const lote = await new Promise((ok, mal) => lector.readEntries(ok, mal));
    if (!lote.length) break;
    todas.push(...lote);
  }
  const res = [];
  for (const e of todas) res.push(...await leerEntrada(e, ruta + entrada.name + "/"));
  return res;
}

function pintarSeleccion() {
  const { archivos, ignorados } = estado;
  $("seleccion").hidden = !archivos.length && !ignorados.length;
  $("tituloSeleccion").textContent = archivos.length
    ? `${plural(archivos.length, "archivo listo", "archivos listos")} de ${estado.info.max_archivos}` : "Ningún archivo listo";
  $("lista").replaceChildren(...archivos.map((a, i) => {
    const movil = esMovil(a.nombre, a.lenguaje);
    return h("li", { class: "archivo" },
      h("span", { class: `lang ${movil ? "movil" : ""}`, title: movil ? "Se evalúa con las reglas de Móvil" : null }, ETIQUETA_LENG[a.lenguaje] || a.lenguaje),
      h("div", {}, h("div", { class: "ruta", title: a.nombre }, a.nombre),
        h("div", { class: "meta" }, kb(a.bytes), movil ? ", reglas de Móvil" : "", a.nota ? `, ${a.nota}` : "")),
      h("button", { type: "button", class: "quitar", "aria-label": `Quitar ${a.nombre}`, onclick: () => { archivos.splice(i, 1); pintarSeleccion(); } }, "×"));
  }));
  $("ignorados").replaceChildren(ignorados.length ? h("div", { class: "aviso adv" },
    h("b", {}, `${plural(ignorados.length, "archivo no se enviará", "archivos no se enviarán")}`),
    h("ul", {}, ignorados.slice(0, 12).map((x) => h("li", {}, h("code", {}, x.nombre), `: ${x.motivo}`)),
      ignorados.length > 12 ? h("li", {}, `y ${ignorados.length - 12} más`) : null),
    h("div", {}, h("button", { type: "button", class: "btn fantasma chico", onclick: () => { estado.ignorados = []; pintarSeleccion(); } }, "Ocultar esta lista"))) : "");
  $("btnRevisar").disabled = !archivos.length;
  $("btnRevisar").textContent = archivos.length ? `Revisar ${plural(archivos.length, "archivo", "archivos")}` : "Revisar";
}

function abrirSelector(input) { input.value = ""; input.click(); }

// ---------------------------------------------------------------- 2. revisar
async function revisar() {
  $("btnRevisar").disabled = true;
  const inicio = Date.now(), usarLlm = $("usarLlm").checked;
  const pintar = () => $("progreso").replaceChildren(h("span", { class: "giro", "aria-hidden": "true" }),
    `Revisando ${plural(estado.archivos.length, "archivo", "archivos")}: ${Math.round((Date.now() - inicio) / 1000)} s` +
    (usarLlm ? ". El especialista puede hacer hasta 8 llamadas al modelo por archivo." : "."));
  pintar();
  const reloj = setInterval(pintar, 1000);
  try {
    estado.revision = await api("/v1/revisiones", {
      tipo_app: document.querySelector("input[name=tipo]:checked").value,
      modo_bd: document.querySelector("input[name=bd]:checked").value, usar_llm: usarLlm,
      archivos: estado.archivos.map(({ nombre, contenido }) => ({ nombre, contenido })) });
    estado.final = null;
    estado.aprobados.clear();
    estado.filtro = "todos";
    const orden = ordenarArchivos(estado.revision.archivos);
    estado.actual = orden[0]?.archivo || null;
    $("vistaCarga").hidden = true;
    $("vistaRevision").hidden = false;
    marcarPaso(2);
    pintarRevision();
    window.scrollTo({ top: 0 });
  } catch (e) {
    avisar(e);
  } finally {
    clearInterval(reloj);
    $("progreso").textContent = "";
    $("btnRevisar").disabled = !estado.archivos.length;
  }
}

const todosLos = (a) => [...a.hallazgos, ...a.semanticos];
const bloqueantes = (a) => todosLos(a).filter((x) => x.severidad === "bloqueante").length;
function ordenarArchivos(lista) {
  return [...lista].sort((x, y) => bloqueantes(y) - bloqueantes(x) || todosLos(y).length - todosLos(x).length);
}
const original = (nombre) => (estado.archivos.find((x) => x.nombre === nombre)?.contenido || "").split(/\r?\n/);

function pintarRevision() {
  pintarVeredicto();
  pintarRail();
  pintarDetalle();
  pintarFinal();
  actualizarBarra();
}

function pintarVeredicto() {
  const r = estado.revision, todos = r.archivos.flatMap(todosLos);
  const v = estado.final ? (estado.final.veredicto_final || estado.final.veredicto_inicial) : r.veredicto_inicial;
  const n = {
    bloq: todos.filter((x) => x.severidad === "bloqueante" && x.confianza === "alta").length,
    media: todos.filter((x) => x.confianza === "media").length,
    adv: todos.filter((x) => x.severidad === "advertencia" && x.confianza === "alta").length,
  };
  const total = Math.max(1, n.bloq + n.media + n.adv);
  const tramo = (k) => { const s = h("span", { class: `c-${k}` }); s.style.width = `${(100 * n[k]) / total}%`; return s; };
  const t = r.totales;
  $("veredicto").replaceChildren(h("section", { class: `veredicto ${v}`, "aria-label": "Veredicto" },
    h("div", {}, h("p", { class: "frase" }, estado.final ? `Tras aplicar lo aprobado: ${VEREDICTO[v][0].toLowerCase()}` : VEREDICTO[v][0]),
      h("p", { class: "por-que" }, VEREDICTO[v][1], ` ${plural(t.archivos, "archivo revisado", "archivos revisados")}, `,
        `${plural(t.parches, "corrección propuesta", "correcciones propuestas")}, ${plural(t.llamadas_llm, "llamada", "llamadas")} al modelo en ${t.segundos} s.`)),
    h("div", { class: "botones-izq" },
      h("button", { type: "button", class: "btn chico", onclick: () => descargar("revision.json", JSON.stringify(estado.final || r, null, 1), "application/json") }, "Descargar reporte"),
      h("button", { type: "button", class: "btn fantasma chico", onclick: nuevaRevision }, "Nueva revisión")),
    h("div", { class: "barra-sev", role: "img", "aria-label": `${n.bloq} bloqueantes, ${n.media} para confirmar, ${n.adv} advertencias` },
      tramo("bloq"), tramo("media"), tramo("adv")),
    h("div", { class: "leyenda" },
      h("span", {}, h("span", { class: "punto c-bloq" }), h("b", {}, n.bloq), "bloqueantes"),
      h("span", {}, h("span", { class: "punto c-media" }), h("b", {}, n.media), "para confirmar a mano"),
      h("span", {}, h("span", { class: "punto c-adv" }), h("b", {}, n.adv), "advertencias"))));
}

function pintarRail() {
  $("rail").replaceChildren(...ordenarArchivos(estado.revision.archivos).map((a) => {
    const partes = a.archivo.split("/"), archivo = partes.pop(), carpeta = partes.join("/");
    const b = bloqueantes(a), n = todosLos(a).length;
    const aprob = a.parches.filter((p) => estado.aprobados.has(clave(a.archivo, p.id))).length;
    const color = a.omitido ? "c-adv" : b ? "c-bloq" : n ? "c-media" : "c-ok";
    return h("button", { type: "button", class: "rail-item", "aria-current": a.archivo === estado.actual ? "true" : "false",
      onclick: () => { estado.actual = a.archivo; estado.filtro = "todos"; pintarRail(); pintarDetalle(); $("detalle").focus({ preventScroll: true }); } },
      h("span", { class: `punto ${color}`, "aria-hidden": "true" }),
      h("span", {}, h("span", { class: "nombre" }, archivo), carpeta ? h("span", { class: "carpeta" }, carpeta) : null),
      h("span", { class: "n" }, a.omitido ? "omitido" : n ? `${n}` : "ok", aprob ? h("span", { class: "aprob", title: "Correcciones aprobadas" }, ` ${aprob} ✓`) : null));
  }));
}

function pintarDetalle() {
  const a = estado.revision.archivos.find((x) => x.archivo === estado.actual);
  if (!a) { $("detalle").replaceChildren(h("p", { class: "vacio" }, "Elige un archivo a la izquierda.")); return; }
  const todos = todosLos(a), lineas = original(a.archivo);
  const cab = h("header", { class: "detalle-cab" }, h("h2", { class: "ruta" }, a.archivo),
    h("div", { class: "etiquetas" }, chip(ETIQUETA_LENG[a.lenguaje] || a.lenguaje),
      a.evaluado_como === "movil" && estado.revision.contexto.tipo_app !== "movil" ? chip("evaluado con reglas de Móvil", "modelo") : null,
      a.omitido ? chip(`omitido: ${a.omitido}`, "adv") : [
        chip(plural(todos.length, "hallazgo", "hallazgos"), todos.length ? "" : "ok"),
        bloqueantes(a) ? chip(plural(bloqueantes(a), "bloqueante", "bloqueantes"), "bloq") : null,
        a.parches.length ? chip(plural(a.parches.length, "corrección", "correcciones"), "cian") : null]));
  const partes = [cab];
  if (a.omitido) { $("detalle").replaceChildren(...partes, h("p", { class: "vacio" }, `Este archivo no se revisó: ${a.omitido}.`)); return; }

  if (todos.length) {
    const filtros = [["todos", "Todos", () => true], ["bloq", "Bloqueantes", (x) => x.severidad === "bloqueante"],
      ["media", "Para confirmar", (x) => x.confianza === "media"], ["adv", "Advertencias", (x) => x.severidad === "advertencia"],
      ["parche", "Con corrección", (x) => a.parches.some((p) => p.hallazgo_id === x.id)]]
      .filter(([k, , f]) => k === "todos" || todos.some(f));
    const activo = filtros.find(([k]) => k === estado.filtro) || filtros[0];
    partes.push(h("div", { class: "filtros", role: "group", "aria-label": "Filtrar hallazgos" }, filtros.map(([k, txt, f]) =>
      h("button", { type: "button", class: "filtro", "aria-pressed": String(k === activo[0]), onclick: () => { estado.filtro = k; pintarDetalle(); } },
        `${txt} (${todos.filter(f).length})`))));
    partes.push(h("div", { class: "hallazgos" }, todos.filter(activo[2]).map((x) => pintarHallazgo(a, x))));
  } else {
    partes.push(h("p", { class: "vacio" }, a.resumen_especialista ? "Sin hallazgos." : "Sin hallazgos de los detectores."));
  }

  if (a.parches.length) {
    partes.push(h("section", { class: "bloque", "aria-label": "Correcciones propuestas" }, h("h3", {}, "Correcciones propuestas"),
      h("p", { class: "tenue" }, "Ya pasaron por la guarda: el archivo corregido se volvió a analizar. Marca las que apruebas."),
      a.parches.map((p) => pintarParche(a, p, lineas))));
  }
  if (a.rechazos_guarda.length) {
    partes.push(h("section", { class: "bloque" }, h("h3", {}, "Rechazadas por la guarda"),
      h("p", { class: "tenue" }, "No llegan a tu aprobación: corregían mal o escondían el problema."),
      h("ul", { class: "lista-simple" }, a.rechazos_guarda.map((r) => h("li", {}, h("code", {}, r.hallazgo), ` ${r.categoria}: ${r.motivo}`)))));
  }
  if (a.resumen_especialista) {
    partes.push(h("section", { class: "bloque" }, h("h3", {}, "Lo que dice el especialista"), h("p", {}, a.resumen_especialista)));
  }
  $("detalle").replaceChildren(...partes);
}

function pintarHallazgo(a, x) {
  const p = a.parches.find((q) => q.hallazgo_id === x.id);
  const manual = a.revision_manual[x.id];
  const accion = p ? h("span", {}, h("b", {}, `Corrección ${p.id}`), " propuesta abajo")
    : manual ? h("span", {}, h("b", {}, "Revisión humana. "), manual)
    : x.confianza === "media" ? "Confírmalo a mano: puede ser un falso positivo." : "";
  return h("article", { class: "hallazgo" },
    h("span", { class: "linea", title: "Línea" }, `L${x.linea}`),
    h("div", { class: "que" },
      h("div", { class: "etiquetas" }, enlaceRegla(x.regla_id), h("span", { class: "titulo-regla" }, x.titulo_regla)),
      h("p", { class: "msg" }, x.mensaje),
      x.fragmento ? h("code", { class: "frag" }, x.fragmento) : null,
      h("div", { class: "etiquetas" }, chip(x.severidad, x.severidad === "bloqueante" ? "bloq" : "adv"),
        x.confianza === "media" ? chip("confianza media", "media") : null,
        a.semanticos.includes(x) ? chip("lo vio el modelo", "modelo") : null)),
    h("p", { class: "accion" }, accion));
}

function pintarParche(a, p, lineas) {
  const k = clave(a.archivo, p.id), cerrado = Boolean(estado.final);
  const final = cerrado ? estado.final.archivos.find((x) => x.archivo === a.archivo)?.parches.find((q) => q.id === p.id) : null;
  const caja = h("input", { type: "checkbox", disabled: cerrado, onchange: (ev) => {
    ev.target.checked ? estado.aprobados.add(k) : estado.aprobados.delete(k);
    tarjeta.classList.toggle("aprobado", ev.target.checked);
    actualizarBarra(); pintarRail();
  } });
  caja.checked = estado.aprobados.has(k);
  const tarjeta = h("article", { class: `parche ${caja.checked ? "aprobado" : ""} ${cerrado ? "cerrado" : ""}` },
    h("div", { class: "parche-cab" },
      h("label", { class: "aprobar" }, caja, `Aprobar ${p.id}`),
      final ? chip(final.estado, final.estado === "aplicado" ? "ok" : final.estado === "conflicto" ? "adv" : "") : null,
      enlaceRegla(p.regla_id), chip(`hallazgo ${p.hallazgo_id}`),
      chip(p.origen === "llm" ? "la propuso el modelo" : "corrección mecánica", p.origen === "llm" ? "modelo" : "cian"),
      h("span", { class: "tenue" }, p.linea_inicio === p.linea_fin ? `línea ${p.linea_inicio}` : `líneas ${p.linea_inicio} a ${p.linea_fin}`)),
    h("div", { class: "cambio" },
      h("div", { class: "lado" }, h("span", {}, "Antes"), h("pre", { class: "antes" }, lineas.slice(p.linea_inicio - 1, p.linea_fin).join("\n"))),
      h("div", { class: "lado" }, h("span", {}, "Después"), h("pre", { class: "despues" }, p.reemplazo))),
    h("p", { class: "justif" }, p.justificacion));
  return tarjeta;
}

// ---------------------------------------------------------------- 3. aprobar y descargar
function totalParches() { return estado.revision ? estado.revision.archivos.reduce((n, a) => n + a.parches.length, 0) : 0; }

function actualizarBarra() {
  const total = totalParches();
  $("barraAprobar").hidden = !estado.revision || Boolean(estado.final) || total === 0;
  $("cuenta").replaceChildren(h("b", {}, estado.aprobados.size), ` de ${plural(total, "corrección aprobada", "correcciones aprobadas")}. Las demás quedarán denegadas.`);
  $("btnAplicar").textContent = estado.aprobados.size ? `Aplicar ${plural(estado.aprobados.size, "aprobada", "aprobadas")}` : "Denegar todas y cerrar";
}

function marcarTodos(valor) {
  for (const a of estado.revision.archivos) for (const p of a.parches) {
    valor ? estado.aprobados.add(clave(a.archivo, p.id)) : estado.aprobados.delete(clave(a.archivo, p.id));
  }
  pintarRail(); pintarDetalle(); actualizarBarra();
}

async function aplicar() {
  $("btnAplicar").disabled = true;
  try {
    const aprobados = [...estado.aprobados].map((k) => { const [archivo, parche] = k.split("\u0000"); return { archivo, parche }; });
    estado.final = await api(`/v1/revisiones/${estado.revision.revision_id}/aprobacion`, { aprobados });
    marcarPaso(3);
    pintarRevision();
    $("final").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (e) {
    avisar(e);
  } finally {
    $("btnAplicar").disabled = false;
  }
}

function pintarDiff(texto) {
  return h("pre", { class: "diff" }, texto.split("\n").map((l) => h("span", {
    class: l.startsWith("@@") ? "arr" : l.startsWith("+") && !l.startsWith("+++") ? "mas" : l.startsWith("-") && !l.startsWith("---") ? "menos" : "" }, l + "\n")));
}

function pintarFinal() {
  const f = estado.final;
  if (!f) { $("final").replaceChildren(); return; }
  const estados = f.archivos.flatMap((a) => a.parches.map((p) => p.estado));
  const cuenta = (e) => estados.filter((x) => x === e).length;
  const quedan = f.archivos.reduce((n, a) => n + (a.hallazgos_despues || 0), 0);
  const partes = [h("div", { class: "resumen" },
    h("div", {}, h("h2", {}, f.corregidos.length ? `${plural(f.corregidos.length, "archivo corregido", "archivos corregidos")}, listos para descargar` : "No hay archivos corregidos"),
      h("p", { class: "tenue" }, `${plural(cuenta("aplicado"), "corrección aplicada", "correcciones aplicadas")}, ${cuenta("denegado")} denegadas`,
        cuenta("conflicto") ? `, ${cuenta("conflicto")} en conflicto con otra` : "", `. Quedan ${plural(quedan, "hallazgo", "hallazgos")} para corregir a mano.`)),
    f.corregidos.length ? h("div", { class: "botones-izq" },
      h("button", { type: "button", class: "btn primario", onclick: () => descargar("cambios.diff", f.corregidos.map((c) => c.diff).join("")) }, "Descargar cambios.diff"),
      h("button", { type: "button", class: "btn", onclick: descargarTodos }, `Descargar ${plural(f.corregidos.length, "archivo", "archivos")}`)) : null)];
  for (const c of f.corregidos) {
    partes.push(h("details", { class: "diff-archivo" },
      h("summary", {}, h("span", { class: "ruta" }, c.archivo),
        h("button", { type: "button", class: "btn chico", onclick: (ev) => { ev.preventDefault(); descargar(base(c.archivo), c.contenido); } }, "Descargar")),
      pintarDiff(c.diff)));
  }
  $("final").replaceChildren(...partes);
}

async function descargarTodos() {
  for (const c of estado.final.corregidos) {   // un archivo por descarga; el navegador puede pedir permiso la primera vez
    descargar(base(c.archivo), c.contenido);
    await new Promise((ok) => setTimeout(ok, 350));
  }
}

function nuevaRevision() {
  estado.revision = estado.final = null;
  estado.aprobados.clear();
  $("vistaRevision").hidden = true;
  $("vistaCarga").hidden = false;
  $("barraAprobar").hidden = true;
  marcarPaso(1);
  pintarSeleccion();
  window.scrollTo({ top: 0 });
}

// ---------------------------------------------------------------- reglas
async function verRegla(id) {
  $("regla").replaceChildren(h("p", { class: "tenue" }, "Cargando la regla…"));
  $("dlgRegla").showModal();
  try {
    const r = await api(`/v1/reglas/${encodeURIComponent(id)}`);
    $("regla").replaceChildren(h("h2", { id: "reglaTitulo" }, `${r.id}: ${r.titulo}`),
      h("div", { class: "etiquetas" }, chip(r.nivel, r.nivel === "Recomendado" ? "adv" : "bloq"), r.aplica_a.map((x) => chip(x))),
      h("p", { class: "cita" }, r.cita), h("div", { class: "texto-regla" }, r.texto));
  } catch (e) {
    $("regla").replaceChildren(h("p", {}, e.title || "No se pudo cargar la regla", ". ", e.detail || ""));
  }
}

// ---------------------------------------------------------------- eventos
const zona = $("zona");
$("btnArchivos").addEventListener("click", (ev) => { ev.stopPropagation(); abrirSelector($("inArchivos")); });
$("btnCarpeta").addEventListener("click", (ev) => { ev.stopPropagation(); abrirSelector($("inCarpeta")); });
$("btnPegar").addEventListener("click", (ev) => { ev.stopPropagation(); $("formPegar").hidden = false; $("pegarNombre").focus(); });
zona.addEventListener("click", (ev) => { if (!ev.target.closest("button, input")) abrirSelector($("inArchivos")); });
zona.addEventListener("keydown", (ev) => { if ((ev.key === "Enter" || ev.key === " ") && ev.target === zona) { ev.preventDefault(); abrirSelector($("inArchivos")); } });
$("inArchivos").addEventListener("change", (ev) => agregar([...ev.target.files].map((f) => ({ file: f, ruta: f.name }))));
$("inCarpeta").addEventListener("change", (ev) => agregar([...ev.target.files].map((f) => ({ file: f, ruta: f.webkitRelativePath || f.name }))));
// Soltar fuera de la zona no debe abrir el archivo en el navegador (y perder la página).
["dragover", "drop"].forEach((t) => window.addEventListener(t, (ev) => ev.preventDefault()));
let profundidad = 0;
zona.addEventListener("dragenter", () => { profundidad++; zona.classList.add("sobre"); });
zona.addEventListener("dragleave", () => { if (--profundidad <= 0) { profundidad = 0; zona.classList.remove("sobre"); } });
zona.addEventListener("drop", async (ev) => {
  profundidad = 0; zona.classList.remove("sobre");
  const items = [...(ev.dataTransfer.items || [])];
  const entradas = items.map((i) => (i.webkitGetAsEntry ? i.webkitGetAsEntry() : null)).filter(Boolean);
  if (entradas.length) {
    const lista = [];
    for (const e of entradas) lista.push(...await leerEntrada(e));
    agregar(lista);
  } else {
    agregar([...ev.dataTransfer.files].map((f) => ({ file: f, ruta: f.name })));
  }
});
$("formPegar").addEventListener("submit", (ev) => {
  ev.preventDefault();
  const nombre = $("pegarNombre").value.trim().replace(/\\/g, "/"), codigo = $("pegarCodigo").value;
  if (!lenguajeDe(nombre)) { $("pegarAviso").textContent = `Usa una extensión de la lista, por ejemplo .cs, .ts o .kt.`; return; }
  const bytes = new TextEncoder().encode(codigo).length;
  const previo = estado.archivos.findIndex((a) => a.nombre === nombre);
  const entrada = { nombre, contenido: codigo, bytes, lenguaje: lenguajeDe(nombre), nota: "pegado" };
  previo >= 0 ? (estado.archivos[previo] = entrada) : estado.archivos.push(entrada);
  $("pegarCodigo").value = ""; $("pegarNombre").value = ""; $("pegarAviso").textContent = `Agregado: ${nombre}`;
  pintarSeleccion();
});
$("btnCancelarPegar").addEventListener("click", () => { $("formPegar").hidden = true; });
$("btnVaciar").addEventListener("click", () => { estado.archivos = []; estado.ignorados = []; pintarSeleccion(); });
document.querySelectorAll("input[name=tipo]").forEach((r) => r.addEventListener("change", () => { $("ayudaTipo").textContent = AYUDA_TIPO[r.value]; }));
document.querySelectorAll("input[name=bd]").forEach((r) => r.addEventListener("change", () => { $("ayudaBd").textContent = AYUDA_BD[r.value]; }));
$("usarLlm").addEventListener("change", (ev) => {
  $("ayudaLlm").textContent = ev.target.checked ? "El modelo propone correcciones y revisa lo que los detectores no ven."
    : "Solo detectores y correcciones mecánicas: más rápido y sin costo.";
});
$("btnRevisar").addEventListener("click", revisar);
$("btnAplicar").addEventListener("click", aplicar);
$("btnTodos").addEventListener("click", () => marcarTodos(true));
$("btnNinguno").addEventListener("click", () => marcarTodos(false));
cargarInfo();
