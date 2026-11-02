"""EST-REF-001 · Marco de referencia de estándares externos (OWASP).

Los identificadores (A03:2021, API1:2023, V5.3.4, MASVS-STORAGE-1) son públicos. Las descripciones son resúmenes
propios en español; no reproducen el texto oficial de OWASP.
"""
from fuentes.comun import R


def T(id, externo, titulo, resumen, internas, nivel="Obligatorio", aplica="Web, API"):
    return R(id, f"{externo} - {titulo}", f"{resumen}\n\nReglas internas relacionadas: {internas}.",
             nivel=nivel, aplica=aplica, refs=externo)


DOC = {
    "codigo": "EST-REF-001",
    "titulo": "Marco de Referencia de Estándares Externos",
    "subtitulo": "OWASP ASVS, MASVS, Top 10 y API Security Top 10",
    "version": "1.3",
    "fecha": "2026-03-10",
    "categoria": "referencia",
    "archivo": "EST-REF-001_marco_referencia_owasp.pdf",
    "aprobado_por": "Seguridad de la Información",
    "historial": [
        ("1.0", "2022-05-02", "Versión inicial: OWASP Top 10 2017."),
        ("1.2", "2024-09-16", "Adopción de ASVS 4.0.3, MASVS 2.0 y Top 10 2021."),
        ("1.3", "2026-03-10", "Se agrega OWASP API Security Top 10 2023 y el grupo MASVS-PRIVACY."),
    ],
    "objetivo": "Indicar qué estándares externos adopta la empresa, en qué versión y con qué nivel de exigencia, "
                "y relacionar cada control externo con las reglas internas que lo implementan.",
    "alcance": "Complementa a EST-SEG-001, EST-API-001, EST-WEB-001 y EST-DSK-001. Este documento es un resumen "
               "interno: ante cualquier duda de interpretación prevalece la publicación oficial de OWASP "
               "(owasp.org). Los textos de cada control son paráfrasis, no traducciones literales.",
    "definiciones": [
        ("OWASP", "Open Worldwide Application Security Project, fundación sin fines de lucro que publica guías "
                  "abiertas de seguridad de aplicaciones."),
        ("Nivel de verificación", "Grado de rigor con que se verifica una aplicación: L1, L2 o L3 en ASVS; "
                                  "MAS-L1, MAS-L2 y MAS-R en MASVS."),
    ],
    "capitulos": [
        {"titulo": "Versiones y niveles adoptados", "reglas": [
            R("REF-NIV-001", "Nivel ASVS exigido según el tipo de aplicación",
              "Nivel L1: aplicaciones internas sin datos sensibles. Nivel L2 (nivel por defecto): toda aplicación "
              "web o API que procese datos sensibles o que esté expuesta a internet. Nivel L3: sistemas "
              "transaccionales core, pagos y aplicaciones que administran identidades. El nivel se registra en la "
              "ficha de arquitectura de cada sistema.",
              aplica="Web, API", refs="OWASP ASVS 4.0.3"),
            R("REF-NIV-002", "Perfil MASVS exigido para aplicaciones móviles",
              "MAS-L1 para aplicaciones informativas. MAS-L2 para aplicaciones que manejan datos de clientes. "
              "Las aplicaciones con transacciones monetarias cumplen MAS-L2 más los controles de resiliencia "
              "(MAS-R). La verificación se realiza con la guía de pruebas MASTG.",
              aplica="Móvil", refs="OWASP MASVS 2.x; OWASP MASTG"),
            R("REF-NIV-003", "Versiones vigentes de los estándares externos",
              "Versiones adoptadas: ASVS 4.0.3 (la migración a ASVS 5.0 está planificada; mientras tanto los "
              "identificadores de requisitos citados en los estándares internos corresponden a la 4.0.3), MASVS "
              "2.x, OWASP Top 10 edición 2021 y OWASP API Security Top 10 edición 2023. Seguridad de la Información "
              "revisa las versiones una vez al año.",
              aplica="Web, Móvil, Escritorio, API", refs="OWASP"),
        ]},
        {"titulo": "OWASP Top 10 (2021)", "intro":
            "Lista de concienciación de los diez riesgos más críticos en aplicaciones web. No es un estándar "
            "verificable por sí mismo: los requisitos verificables están en ASVS.",
         "reglas": [
            T("REF-T10-A01", "A01:2021", "Pérdida de control de acceso",
              "Usuarios que actúan fuera de sus permisos: acceso a datos de otros usuarios cambiando "
              "identificadores, elevación de privilegios, APIs sin control de acceso en operaciones de escritura.",
              "SEG-GEN-002, SEG-GEN-003, SEG-ACC-001, SEG-ACC-002, SEG-ACC-003"),
            T("REF-T10-A02", "A02:2021", "Fallas criptográficas",
              "Datos sensibles sin cifrar en tránsito o en reposo, algoritmos débiles u obsoletos, claves "
              "embebidas en el código y generación de aleatorios predecibles.",
              "SEG-AUT-002, SEG-CRI-001, SEG-CRI-002, SEG-CRI-004, SEG-CRI-005"),
            T("REF-T10-A03", "A03:2021", "Inyección",
              "Datos no confiables interpretados como comandos o consultas: SQL, comandos del sistema operativo, "
              "LDAP y XSS (que en esta edición se incluye en inyección).",
              "SEG-INY-001, SEG-INY-002, SEG-INY-003, SEG-INY-004"),
            T("REF-T10-A04", "A04:2021", "Diseño inseguro",
              "Debilidades de diseño que ninguna implementación perfecta corrige: ausencia de modelado de "
              "amenazas, flujos de negocio sin límites, falta de controles en la arquitectura.",
              "SEG-GEN-001, SEG-INY-007, SEG-CFG-004"),
            T("REF-T10-A05", "A05:2021", "Configuración de seguridad incorrecta",
              "Configuraciones por defecto, mensajes de error detallados, cabeceras de seguridad ausentes, CORS "
              "permisivo, servicios innecesarios habilitados y procesadores XML con entidades externas.",
              "SEG-CRI-003, SEG-LOG-003, SEG-CFG-001, SEG-CFG-002, SEG-INY-006"),
            T("REF-T10-A06", "A06:2021", "Componentes vulnerables y desactualizados",
              "Uso de bibliotecas, frameworks o plataformas con vulnerabilidades conocidas o sin soporte del "
              "fabricante, y falta de un inventario de dependencias.",
              "SEG-CFG-003, SEG-CFG-004"),
            T("REF-T10-A07", "A07:2021", "Fallas de identificación y autenticación",
              "Contraseñas débiles, falta de protección contra fuerza bruta, ausencia de MFA, manejo inseguro "
              "de sesiones y tokens.",
              "SEG-AUT-001 a SEG-AUT-006"),
            T("REF-T10-A08", "A08:2021", "Fallas de integridad de software y datos",
              "Deserialización insegura, actualizaciones sin verificación de firma y pipelines de CI/CD que "
              "permiten introducir código no autorizado.",
              "SEG-INY-005, SEG-DSK-003"),
            T("REF-T10-A09", "A09:2021", "Fallas en el registro y monitoreo",
              "Eventos de seguridad no registrados, logs sin información útil o con datos sensibles, y ausencia "
              "de alertas que permitan detectar un ataque en curso.",
              "SEG-LOG-001, SEG-LOG-002"),
            T("REF-T10-A10", "A10:2021", "Falsificación de solicitudes del lado del servidor (SSRF)",
              "El servidor realiza peticiones a una URL que controla el atacante, lo que permite alcanzar "
              "servicios internos o metadatos de la nube.",
              "API-SEG-005"),
        ]},
        {"titulo": "OWASP API Security Top 10 (2023)", "reglas": [
            T("REF-API-01", "API1:2023", "Autorización rota a nivel de objeto (BOLA)",
              "La API no verifica que el usuario tenga derecho sobre el objeto concreto cuyo identificador recibe.",
              "SEG-ACC-002, API-SEG-002", aplica="API"),
            T("REF-API-02", "API2:2023", "Autenticación rota",
              "Mecanismos de autenticación mal implementados: tokens sin validar, credenciales en la URL, falta de "
              "límites de intentos.",
              "SEG-AUT-004, SEG-AUT-006, API-SEG-001", aplica="API"),
            T("REF-API-03", "API3:2023", "Autorización rota a nivel de propiedad",
              "La API expone propiedades que el usuario no debería ver o permite modificar propiedades que no "
              "debería cambiar (asignación masiva).",
              "API-RES-004", aplica="API"),
            T("REF-API-04", "API4:2023", "Consumo de recursos sin restricción",
              "Ausencia de límites de tasa, de tamaño de petición, de paginación o de tiempo de ejecución, lo que "
              "permite denegación de servicio o costos elevados.",
              "SEG-AUT-004, API-RES-003, API-SEG-003", aplica="API"),
            T("REF-API-05", "API5:2023", "Autorización rota a nivel de función",
              "Usuarios comunes pueden invocar operaciones administrativas porque la autorización no se aplica a "
              "nivel de operación.",
              "API-SEG-002", aplica="API"),
            T("REF-API-06", "API6:2023", "Acceso sin restricción a flujos de negocio sensibles",
              "Flujos como compras, reservas o registros pueden automatizarse de forma abusiva al no existir "
              "controles anti-automatización.",
              "SEG-AUT-004, API-SEG-003, API-NET-005", aplica="API"),
            T("REF-API-07", "API7:2023", "Falsificación de solicitudes del lado del servidor (SSRF)",
              "La API obtiene recursos remotos a partir de URLs proporcionadas por el usuario sin validarlas.",
              "API-SEG-005", aplica="API"),
            T("REF-API-08", "API8:2023", "Configuración de seguridad incorrecta",
              "CORS permisivo, cabeceras ausentes, métodos HTTP innecesarios, documentación interactiva expuesta "
              "en producción, mensajes de error detallados.",
              "SEG-CFG-001, SEG-CFG-002, API-GOB-002", aplica="API"),
            T("REF-API-09", "API9:2023", "Gestión inadecuada del inventario",
              "Versiones antiguas o APIs no documentadas siguen expuestas sin control ni dueño.",
              "API-VER-002, API-GOB-001", aplica="API"),
            T("REF-API-10", "API10:2023", "Consumo inseguro de APIs",
              "Se confía ciegamente en las respuestas de APIs de terceros sin validarlas ni limitar su impacto.",
              "API-SEG-006", aplica="API"),
        ]},
        {"titulo": "OWASP ASVS 4.0.3 por capítulo", "intro":
            "Resumen de los catorce capítulos de ASVS 4.0.3 con los requisitos más citados en los estándares "
            "internos. La lista completa de requisitos se consulta en la publicación oficial.",
         "reglas": [
            T("REF-ASVS-V1", "ASVS V1", "Arquitectura, diseño y modelado de amenazas",
              "Ciclo de desarrollo seguro, modelado de amenazas para cada cambio de diseño (V1.1.2) y "
              "arquitectura con controles centralizados.", "SEG-GEN-001"),
            T("REF-ASVS-V2", "ASVS V2", "Autenticación",
              "Contraseñas de al menos 12 caracteres (V2.1.1), verificación contra contraseñas filtradas (V2.1.7), "
              "controles anti-automatización (V2.2.1) y almacenamiento con funciones de derivación de claves con "
              "sal (V2.4.1).", "SEG-AUT-001, SEG-AUT-002, SEG-AUT-004"),
            T("REF-ASVS-V3", "ASVS V3", "Gestión de sesiones",
              "Invalidación de la sesión al cerrarla (V3.3.1), atributos Secure (V3.4.1), HttpOnly (V3.4.2) y "
              "SameSite (V3.4.3) en las cookies.", "SEG-AUT-005"),
            T("REF-ASVS-V4", "ASVS V4", "Control de acceso",
              "Control de acceso aplicado en una capa de confianza del servidor (V4.1.1), mínimo privilegio "
              "(V4.1.3), denegar por defecto (V4.1.5), protección contra IDOR (V4.2.1) y CSRF (V4.2.2).",
              "SEG-GEN-002, SEG-GEN-003, SEG-ACC-001, SEG-ACC-002, SEG-ACC-003"),
            T("REF-ASVS-V5", "ASVS V5", "Validación, sanitización y codificación",
              "Validación por lista blanca (V5.1.3), codificación de salida según el contexto (V5.3.3), consultas "
              "parametrizadas (V5.3.4), prevención de inyección de comandos (V5.3.8), XML sin entidades externas "
              "(V5.5.2) y no deserializar datos no confiables (V5.5.3).",
              "SEG-INY-001 a SEG-INY-006"),
            T("REF-ASVS-V6", "ASVS V6", "Criptografía almacenada",
              "Algoritmos aprobados (V6.2.2), aleatorios criptográficamente seguros (V6.3.1) y gestión de secretos "
              "en una bóveda (V6.4.1).", "SEG-CRI-001, SEG-CRI-002, SEG-CRI-003, SEG-DSK-002"),
            T("REF-ASVS-V7", "ASVS V7", "Manejo de errores y registro",
              "No registrar credenciales ni datos de pago (V7.1.1), registrar eventos de seguridad (V7.1.3) y "
              "mostrar mensajes de error genéricos (V7.4.1).", "SEG-LOG-001, SEG-LOG-002, SEG-LOG-003"),
            T("REF-ASVS-V8", "ASVS V8", "Protección de datos",
              "Clasificación y protección de datos sensibles, cabeceras anti-caché y envío de datos sensibles en "
              "el cuerpo o cabeceras y nunca en la URL (V8.3.1).", "SEG-CRI-005, API-SEG-007"),
            T("REF-ASVS-V9", "ASVS V9", "Comunicaciones",
              "TLS en todas las conexiones de clientes (V9.1.1) y en las comunicaciones internas entre servicios.",
              "SEG-CRI-004"),
            T("REF-ASVS-V10", "ASVS V10", "Código malicioso",
              "Integridad del código y de las actualizaciones, ausencia de funcionalidades ocultas o puertas "
              "traseras.", "SEG-DSK-003, SEG-CFG-004"),
            T("REF-ASVS-V11", "ASVS V11", "Lógica de negocio",
              "Los flujos de negocio se procesan en orden, con límites realistas y protección contra "
              "automatización abusiva.", "API-NET-005, API-SEG-003"),
            T("REF-ASVS-V12", "ASVS V12", "Archivos y recursos",
              "Límite de tamaño de archivos (V12.1.1) y no usar el nombre proporcionado por el usuario para "
              "construir rutas (V12.3.1).", "SEG-INY-007"),
            T("REF-ASVS-V13", "ASVS V13", "API y servicios web",
              "Las URLs no exponen información sensible como claves de API (V13.1.3), los métodos HTTP se validan "
              "(V13.2.1) y la entrada JSON se valida contra un esquema (V13.2.2).",
              "API-DIS-002, API-SEG-001, API-SEG-004"),
            T("REF-ASVS-V14", "ASVS V14", "Configuración",
              "Componentes actualizados (V14.2.1), cabeceras de seguridad como CSP (V14.4.3) y HSTS (V14.4.5), "
              "y CORS con lista blanca de orígenes (V14.5.3).", "SEG-CFG-001, SEG-CFG-002, SEG-CFG-003"),
        ]},
        {"titulo": "OWASP MASVS 2.x por grupo de controles", "reglas": [
            T("REF-MAS-STORAGE", "MASVS-STORAGE", "Almacenamiento",
              "STORAGE-1: los datos sensibles se almacenan de forma segura. STORAGE-2: la aplicación previene la "
              "fuga de datos sensibles (logs, capturas, copias de seguridad).",
              "SEG-MOV-001, SEG-MOV-002, SEG-LOG-001", aplica="Móvil"),
            T("REF-MAS-CRYPTO", "MASVS-CRYPTO", "Criptografía",
              "CRYPTO-1: se usa criptografía robusta según las buenas prácticas. CRYPTO-2: las claves se "
              "gestionan según las buenas prácticas (almacén seguro de la plataforma).",
              "SEG-CRI-001, SEG-MOV-001", aplica="Móvil"),
            T("REF-MAS-AUTH", "MASVS-AUTH", "Autenticación y autorización",
              "AUTH-1: protocolos seguros de autenticación y autorización con el backend. AUTH-2: autenticación "
              "local segura según la plataforma. AUTH-3: autenticación adicional para operaciones sensibles.",
              "SEG-AUT-001, SEG-AUT-003, SEG-MOV-004", aplica="Móvil"),
            T("REF-MAS-NETWORK", "MASVS-NETWORK", "Comunicación de red",
              "NETWORK-1: todo el tráfico de red es seguro según las buenas prácticas. NETWORK-2: se fija la "
              "identidad de los endpoints remotos bajo el control del desarrollador (pinning).",
              "SEG-CRI-004, SEG-MOV-003", aplica="Móvil"),
            T("REF-MAS-PLATFORM", "MASVS-PLATFORM", "Interacción con la plataforma",
              "PLATFORM-1: uso seguro de mecanismos de comunicación entre procesos. PLATFORM-2: uso seguro de "
              "WebViews. PLATFORM-3: uso seguro de la interfaz de usuario.",
              "SEG-MOV-002, SEG-MOV-005", aplica="Móvil"),
            T("REF-MAS-CODE", "MASVS-CODE", "Calidad del código",
              "CODE-1: versión de plataforma actualizada. CODE-2: mecanismo para forzar actualizaciones. CODE-3: "
              "solo componentes sin vulnerabilidades conocidas. CODE-4: validación y sanitización de toda entrada "
              "no confiable.", "SEG-MOV-007, SEG-CFG-003, SEG-INY-002", aplica="Móvil"),
            T("REF-MAS-RESILIENCE", "MASVS-RESILIENCE", "Resiliencia ante ingeniería inversa y manipulación",
              "RESILIENCE-1: valida la integridad de la plataforma. RESILIENCE-2: mecanismos anti-manipulación. "
              "RESILIENCE-3: dificulta el análisis estático. RESILIENCE-4: dificulta el análisis dinámico.",
              "SEG-MOV-006", nivel="Recomendado", aplica="Móvil"),
            T("REF-MAS-PRIVACY", "MASVS-PRIVACY", "Privacidad",
              "PRIVACY-1: minimiza el acceso a datos y recursos sensibles. PRIVACY-2: previene la identificación "
              "del usuario. PRIVACY-3: es transparente sobre la recolección y uso de datos. PRIVACY-4: ofrece al "
              "usuario control sobre sus datos.", "SEG-MOV-008", aplica="Móvil"),
        ]},
    ],
    "cierre": [
        ("Fuentes oficiales", "OWASP Top 10: owasp.org/Top10. OWASP API Security Top 10: owasp.org/API-Security. "
                              "OWASP ASVS: owasp.org/www-project-application-security-verification-standard. "
                              "OWASP MASVS y MASTG: mas.owasp.org. Los contenidos de OWASP se publican bajo licencia "
                              "Creative Commons BY-SA."),
    ],
}
