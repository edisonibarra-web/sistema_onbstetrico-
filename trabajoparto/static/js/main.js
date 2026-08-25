// Configuración de la API
// La URL base se obtiene desde config.js (AppConfig.API_BASE_URL)
// Asegúrate de que config.js se cargue antes que main.js en el HTML
// Base SOLO hasta /api → http://localhost:<puerto-actual>/api (sin rutas adicionales)
// El backend se sirve desde el mismo proceso Django que el frontend, así que el
// puerto correcto es siempre el de la página actual (window.location.port), nunca
// un valor fijo — de lo contrario, correr el servidor en un puerto distinto a 8000
// (ej. pruebas, staging) rompe todas las llamadas a la API.
const HOST_FALLBACK = (window.location.hostname && window.location.hostname !== '0.0.0.0')
    ? window.location.hostname
    : 'localhost';
const PORT_FALLBACK = window.location.port ? `:${window.location.port}` : '';
const API_BASE_URL = (typeof AppConfig !== 'undefined' && AppConfig.API_BASE_URL)
    ? AppConfig.API_BASE_URL
    : `${window.location.protocol}//${HOST_FALLBACK}${PORT_FALLBACK}/api`; // Fallback dinámico sin IP ni puerto fijos
const API_BASE = API_BASE_URL; // Alias: usar en fetch(`${API_BASE}/pacientes/...`)
const LAST_API_BASE_KEY = 'clinico:last_api_base_url';

function normalizarBaseApi(url) {
    return String(url || '').trim().replace(/\/$/, '');
}

function getApiBaseCandidates() {
    const host = (window.location.hostname && window.location.hostname !== '0.0.0.0')
        ? window.location.hostname
        : 'localhost';
    const proto = window.location.protocol === 'https:' ? 'https:' : 'http:';
    const port = window.location.port ? `:${window.location.port}` : '';
    const remembered = localStorage.getItem(LAST_API_BASE_KEY);

    const candidates = [
        API_BASE_URL,
        remembered,
        `${proto}//${host}${port}/api`,
        `${proto}//localhost${port}/api`,
        `${proto}//127.0.0.1${port}/api`,
    ]
        .map(normalizarBaseApi)
        .filter(Boolean);

    return [...new Set(candidates)];
}

async function fetchWithTimeout(url, options, timeoutMs) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
        const response = await fetch(url, { ...options, signal: controller.signal });
        return response;
    } finally {
        clearTimeout(timer);
    }
}

// Utilidades
function getCSRFToken() {
    return document.cookie
      .split('; ')
      .find(row => row.startsWith('csrftoken='))
      ?.split('=')[1];
  }

function calcularEdad(fechaNacimiento) {
    if (!fechaNacimiento) {
        console.warn('⚠️ calcularEdad: No se proporcionó fecha de nacimiento');
        return null;
    }
    
    const hoy = new Date();
    const nacimiento = new Date(fechaNacimiento);
    
    // Validar que la fecha sea válida
    if (isNaN(nacimiento.getTime())) {
        console.error('❌ calcularEdad: Fecha de nacimiento inválida:', fechaNacimiento);
        return null;
    }
    
    // Si la fecha de nacimiento es futura, retornar 0 o null según prefieras
    if (nacimiento > hoy) {
        console.warn('⚠️ calcularEdad: Fecha de nacimiento es futura:', fechaNacimiento);
        return 0; // O podrías retornar null si prefieres
    }
    
    let edad = hoy.getFullYear() - nacimiento.getFullYear();
    const mes = hoy.getMonth() - nacimiento.getMonth();
    
    if (mes < 0 || (mes === 0 && hoy.getDate() < nacimiento.getDate())) {
        edad--;
    }
    
    // Asegurar que la edad no sea negativa
    return Math.max(0, edad);
}

function getLiveElementById(id) {
    const el = document.getElementById(id);
    return el && el.isConnected ? el : null;
}

function mostrarAutoGuardado() {
    const ahora = Date.now();
    // Evita mostrar múltiples toasts seguidos al escribir rápido.
    if (window._ultimoAutoGuardadoTs && (ahora - window._ultimoAutoGuardadoTs) < 1200) {
        return;
    }
    window._ultimoAutoGuardadoTs = ahora;
    mostrarMensaje('Dato guardado automáticamente', 'success');
}

function cerrarModalDesdeElemento(el, delayMs = 150) {
    const modal = el ? el.closest('.modal-parametro') : null;
    if (!modal || !modal.id) return;
    const match = modal.id.match(/^modal-parametro-(\d+)$/);
    if (!match || !match[1]) return;
    setTimeout(() => cerrarModalParametro(match[1]), delayMs);
}

function obtenerValorInput(id, fallback = '') {
    const el = getLiveElementById(id);
    if (!el || typeof el.value === 'undefined') return fallback;
    return el.value;
}

function setValorInput(id, value) {
    const el = getLiveElementById(id);
    if (!el || typeof el.value === 'undefined') return false;
    el.value = value;
    return true;
}

// Resalta visualmente y hace scroll hasta el/los campo(s) que faltan por
// diligenciar al guardar, en vez de solo mostrar un mensaje genérico.
function resaltarCamposFaltantes(idsCampos) {
    let primerElemento = null;
    (idsCampos || []).forEach((id) => {
        const el = getLiveElementById(id);
        if (!el) return;
        if (!primerElemento) primerElemento = el;
        el.classList.remove('campo-faltante-highlight');
        void el.offsetWidth; // fuerza reflow para reiniciar la animación si ya estaba resaltado
        el.classList.add('campo-faltante-highlight');
        setTimeout(() => el.classList.remove('campo-faltante-highlight'), 2600);
    });
    if (primerElemento) {
        primerElemento.scrollIntoView({ behavior: 'smooth', block: 'center' });
        if (typeof primerElemento.focus === 'function') {
            setTimeout(() => primerElemento.focus({ preventScroll: true }), 300);
        }
    }
}

function obtenerDatosFormulario() {
    return {
        codigo: obtenerValorInput('codigo'),
        version: obtenerValorInput('version'),
        fecha_elabora: obtenerValorInput('fecha_elabora'),
        num_hoja: obtenerValorInput('num_hoja'),
        estado: obtenerValorInput('estado'),
        diagnostico: obtenerValorInput('diagnostico'),
        edad_snapshot: obtenerValorInput('edad_snapshot'),
        edad_gestion: obtenerValorInput('edad_gestion'),
        n_controles_prenatales: obtenerValorInput('n_controles_prenatales'),
        gestas: obtenerValorInput('gestas'),
        partos: obtenerValorInput('partos'),
        cesareas: obtenerValorInput('cesareas'),
        abortos: obtenerValorInput('abortos'),
        responsable: obtenerValorInput('responsable'),
        paciente: obtenerValorInput('paciente_id'),
        aseguradora_nombre: (obtenerValorInput('aseguradora_nombre') || '').trim()
    };
}
  
// El event listener del formulario está en el bloque DOMContentLoaded principal (línea ~337)
  

async function apiRequest(endpoint, method = 'GET', data = null) {
    const methodUpper = String(method || 'GET').toUpperCase();
    const options = {
        method: methodUpper,
        headers: {},
        credentials: 'same-origin', // Envía la cookie de sesión para que la API reconozca al usuario autenticado
    };

    // Evita preflight innecesario en GET: no enviar headers custom.
    if (methodUpper !== 'GET') {
        options.headers['Content-Type'] = 'application/json';
        options.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate';
        options.headers['Pragma'] = 'no-cache';
        options.headers['Expires'] = '0';
    }

    const csrfToken = getCSRFToken();
    if (csrfToken && methodUpper !== 'GET') {
        options.headers['X-CSRFToken'] = csrfToken;
    }

    if (data) {
        options.body = JSON.stringify(data);
    }

    const timeoutMs = (typeof AppConfig !== 'undefined' && AppConfig.REQUEST_TIMEOUT)
        ? AppConfig.REQUEST_TIMEOUT
        : 12000;
    const bases = getApiBaseCandidates();
    let ep = endpoint;
    let response = null;
    let url = '';
    let lastNetworkError = null;

    for (const base of bases) {
        // Evitar duplicar /api: si la base ya termina en /api y el endpoint empieza con /api/, quitar /api del endpoint
        ep = endpoint;
        if (base.endsWith('/api') && /^\/api(\/|$)/.test(ep)) {
            ep = ep.replace(/^\/api/, '') || '/';
        }

        // Agregar timestamp si no está presente en la URL para evitar caché
        url = `${base}${ep}`;
        if (methodUpper === 'GET' && !url.includes('?_=')) {
            url += (url.includes('?') ? '&' : '?') + '_=' + new Date().getTime();
        }

        console.log(`🌐 Haciendo petición ${method} a: ${url}`);
        if (data) {
            console.log('📤 Datos enviados:', data);
        }

        try {
            response = await fetchWithTimeout(url, options, timeoutMs);
            console.log(`Respuesta recibida: ${response.status} ${response.statusText}`);
            localStorage.setItem(LAST_API_BASE_KEY, normalizarBaseApi(base));
            break;
        } catch (error) {
            lastNetworkError = error;
            console.warn(`⚠️ Error de red con base ${base}:`, error?.message || error);
            response = null;
        }
    }

    if (!response) {
        const networkMsg = 'No se pudo conectar al backend. Verifique IP/puerto o conectividad de red.';
        mostrarMensaje(networkMsg, 'error');
        throw new Error(lastNetworkError?.message || networkMsg);
    }

    if (!response.ok) {
        const text = await response.text();
        console.error(`Error en la respuesta:`, {
            status: response.status,
            statusText: response.statusText,
            body: text
        });
        
        // Intentar parsear como JSON si es posible
        let errorMessage = text || 'Error en la petición';
        let errorDetails = {};
        
        try {
            const errorJson = JSON.parse(text);
            errorDetails = errorJson;
            
            if (errorJson.detail) {
                errorMessage = errorJson.detail;
            } else if (errorJson.message) {
                errorMessage = errorJson.message;
            } else if (typeof errorJson === 'object') {
                // Si hay errores de validación, mostrarlos
                const validationErrors = Object.entries(errorJson)
                    .map(([key, value]) => {
                        const fieldName = key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
                        const errorText = Array.isArray(value) ? value.join(', ') : value;
                        return `${fieldName}: ${errorText}`;
                    })
                    .join('\n');
                if (validationErrors) {
                    errorMessage = validationErrors;
                }
            }
        } catch (e) {
            // Si no es JSON, usar el texto tal cual
        }
        
        // Mostrar mensaje en la interfaz en lugar de alerta
        mostrarMensaje(errorMessage, 'error');
        
        throw new Error(errorMessage);
    }

    // Solo intentar JSON si hay contenido
    if (response.status === 204) {
        return null;
    }

    const jsonData = await response.json();
    
    // Log de datos recibidos para respuestas exitosas
    if (response.ok) {
        console.log(`📦 Datos recibidos:`, jsonData);
    }
    
    return jsonData;
}


// Cargar aseguradoras en datalist (sugerencias para input de texto)
async function cargarAseguradoras() {
    try {
        const aseguradoras = await apiRequest('/aseguradoras/');
        const datalist = document.getElementById('aseguradora-list');
        
        if (!datalist) return;
        
        datalist.innerHTML = '';
        aseguradoras.forEach(aseguradora => {
            const option = document.createElement('option');
            option.value = aseguradora.nombre;
            datalist.appendChild(option);
        });
    } catch (error) {
        console.error('Error al cargar aseguradoras:', error);
        mostrarMensaje('Error al cargar aseguradoras', 'error');
    }
}

// Buscar paciente por número de identificación
async function buscarPaciente() {
    const numIdentificacion = (obtenerValorInput('num_identificacion') || '').trim();
    const btnBuscar = getLiveElementById('btnBuscarPaciente');
    
    if (!numIdentificacion) {
        mostrarMensaje('Ingrese número de identificación', 'error');
        return;
    }
    
    // Estado de carga visual
    const originalText = btnBuscar ? btnBuscar.innerHTML : '';
    if (btnBuscar) {
        btnBuscar.disabled = true;
        btnBuscar.innerHTML = '⌛ Buscando...';
    }
    
    try {
        const data = await buscarPacienteCompleto(numIdentificacion);
        if (data && data.encontrado) {
            await llenarFormularioDesdePaciente(data);
            mostrarMensaje('Paciente encontrado', 'success');
        } else {
            mostrarMensaje(data.mensaje || 'Paciente no encontrado', 'info');
            limpiarFormulario();
            const numIdentEl = getLiveElementById('num_identificacion');
            if (numIdentEl) numIdentEl.value = numIdentificacion;
        }
    } catch (error) {
        console.error('Error al buscar paciente:', error);
        mostrarMensaje('Error al buscar paciente: ' + error.message, 'error');
    } finally {
        // Restaurar estado del botón
        if (btnBuscar) {
            btnBuscar.disabled = false;
            btnBuscar.innerHTML = originalText;
        }
    }
}

// Función auxiliar para buscar datos obstétricos (reutilizable)
async function buscarDatosObstetricos(cedula) {
    if (!cedula) {
        const numIdentificacionField = document.getElementById("num_identificacion");
        cedula = numIdentificacionField?.value;
    }
    
    if (!cedula) return null;

    try {
        // REUTILIZAR buscarPacienteCompleto que ya tiene caché y lógica consolidada
        const data = await buscarPacienteCompleto(cedula);
        
        if (!data || !data.encontrado) return null;
        
        // Mapear campos para compatibilidad si el formato del backend cambió
        const p = data.paciente || {};
        
        // Llenar campos del formulario
        const nombreField = document.getElementById("nombre");
        if (nombreField) nombreField.value = p.nombre_completo || data.nombres || '';
        
        const nombresField = document.getElementById("nombres");
        if (nombresField) nombresField.value = p.nombre_completo || data.nombres || '';

        const edadGestacionalField = document.getElementById("edad_gestacional") || document.getElementById("edad_gestion");
        if (edadGestacionalField) edadGestacionalField.value = data.edad_gestacional || p.edad_gestacional || '';
        
        const gField = document.getElementById("g");
        if (gField) gField.value = data.g !== undefined ? data.g : (p.g || '');
        
        const pField = document.getElementById("p");
        if (pField) pField.value = data.p !== undefined ? data.p : (p.p || '');
        
        const cField = document.getElementById("c");
        if (cField) cField.value = data.c !== undefined ? data.c : (p.c || '');
        
        const aField = document.getElementById("a");
        if (aField) aField.value = data.a !== undefined ? data.a : (p.a || '');
        
        const grupoSanguineoField = document.getElementById("grupo_sanguineo") || document.getElementById("tipo_sangre");
        if (grupoSanguineoField) grupoSanguineoField.value = data.grupo_sanguineo || p.grupo_sanguineo || '';
        
        const controlesPrenatalesField = document.getElementById("controles_prenatales") || document.getElementById("n_controles_prenatales");
        if (controlesPrenatalesField) controlesPrenatalesField.value = data.n_controles_prenatales || p.n_controles_prenatales || '';
        
        const diagnosticoField = document.getElementById("diagnostico");
        if (diagnosticoField && data.diagnostico) diagnosticoField.value = data.diagnostico;

        const historiaField = document.getElementById("num_historia_clinica");
        if (historiaField) historiaField.value = p.num_historia_clinica || '';

        console.log('✅ Datos obstétricos cargados desde consolidado:', data);
        return data;
    } catch (error) {
        console.error("Error al buscar datos obstétricos:", error);
        throw error;
    }
}

// Buscar paciente obstétrico desde HCMWINGIN (función pública para el botón)
async function buscarPacienteObstetrico() {
    // Sincronizar campo cedula con num_identificacion
    const numIdentificacionField = document.getElementById("num_identificacion");
    const cedulaField = document.getElementById("cedula");
    
    if (numIdentificacionField && cedulaField) {
        cedulaField.value = numIdentificacionField.value;
    }
    
    const cedula = cedulaField?.value || numIdentificacionField?.value;

    if (!cedula) {
        mostrarMensaje("Ingrese la cédula", "error");
        return;
    }

    // Deshabilitar botón mientras busca
    const btnObstetrico = document.getElementById("btn-buscar-obstetrico");
    if (btnObstetrico) {
        btnObstetrico.disabled = true;
        btnObstetrico.textContent = "Buscando...";
    }

    try {
        const data = await buscarDatosObstetricos(cedula);
        
        if (data) {
            mostrarMensaje('Datos obstétricos cargados correctamente', 'success');
        } else {
            mostrarMensaje('Paciente sin datos obstétricos en HCMWINGIN', 'info');
        }
    } catch (error) {
        console.error("Error:", error);
        if (error.message !== "404") {
            mostrarMensaje("Error al buscar paciente obstétrico: " + error.message, "error");
        }
    } finally {
        // Rehabilitar botón
        if (btnObstetrico) {
            btnObstetrico.disabled = false;
            btnObstetrico.textContent = "👶 Obstétrico";
        }
    }
}

// Normaliza el texto libre de "grupo sanguíneo" al formato exacto que exige
// Paciente.tipo_sangre (choices=TipoSangre: O+/O-/A+/A-/B+/B-/AB+/AB-), ya que
// el campo es un input de texto libre y el backend sigue validando ese choice
// exacto — evita que un valor como "o+" o "AB positivo" sea rechazado con un
// error crudo de DRF en vez de guardarse correctamente.
function normalizarTipoSangre(valor) {
    if (!valor) return null;
    const texto = String(valor).trim().toUpperCase();
    const mLetra = texto.match(/\b(AB|A|B|O)\b/);
    if (!mLetra) return null;
    let signo = null;
    if (/NEGATIVO|\bNEG\b|-/.test(texto)) signo = '-';
    else if (/POSITIVO|\bPOS\b|\+/.test(texto)) signo = '+';
    if (!signo) return null;
    return mLetra[1] + signo;
}

// Crear o actualizar paciente
async function guardarPaciente() {
    console.log('Iniciando guardarPaciente...');
    
    const numHistoriaClinica = obtenerValorInput('num_historia_clinica');
    const numIdentificacion = obtenerValorInput('num_identificacion');
    const nombres = obtenerValorInput('nombres');
    
    // Validar campos requeridos
    if (!numHistoriaClinica || !numIdentificacion || !nombres) {
        const camposFaltantes = [];
        const idsFaltantes = [];
        if (!numHistoriaClinica) { camposFaltantes.push('N° historia clinica'); idsFaltantes.push('num_historia_clinica'); }
        if (!numIdentificacion) { camposFaltantes.push('Identificación'); idsFaltantes.push('num_identificacion'); }
        if (!nombres) { camposFaltantes.push('Nombre'); idsFaltantes.push('nombres'); }

        const errorMessage = `Campos de paciente requeridos faltantes: ${camposFaltantes.join(', ')}`;
        mostrarMensaje(errorMessage, 'error');
        resaltarCamposFaltantes(idsFaltantes);
        throw new Error(errorMessage);
    }
    
    const pacienteData = {
        num_historia_clinica: numHistoriaClinica,
        num_identificacion: numIdentificacion,
        nombres: nombres,
        tipo_sangre: normalizarTipoSangre(obtenerValorInput('tipo_sangre')),
        fecha_nacimiento: obtenerValorInput('fecha_elabora_paciente') || null,
    };
    
    console.log('Datos del paciente a guardar:', pacienteData);
    
    const pacienteId = obtenerValorInput('paciente_id');
    console.log('Paciente ID actual:', pacienteId || 'Nuevo paciente');
    
    try {
        let paciente;
        if (pacienteId) {
            console.log(`Actualizando paciente existente con ID: ${pacienteId}`);
            // Actualizar paciente existente
            paciente = await apiRequest(`/pacientes/${pacienteId}/`, 'PUT', pacienteData);
            console.log('Paciente actualizado:', paciente);
        } else {
            console.log('Creando nuevo paciente...');
            // Crear nuevo paciente
            paciente = await apiRequest('/pacientes/', 'POST', pacienteData);
            console.log('Paciente creado:', paciente);
            if (paciente && paciente.id) {
                setValorInput('paciente_id', paciente.id);
                console.log('ID del paciente guardado:', paciente.id);
            }
        }
        
        return paciente;
    } catch (error) {
        console.error('Error al guardar paciente:', error);
        console.error('Detalles del error:', {
            message: error.message,
            stack: error.stack
        });
        
        // Mostrar mensaje más descriptivo
        let mensajeError = 'Error al guardar paciente: ';
        let alertMessage = '';
        
        if (error.message.includes('num_historia_clinica') || error.message.includes('historia clínica')) {
            mensajeError = 'Error al guardar paciente';
        } else if (error.message.includes('num_identificacion') || error.message.includes('identificación')) {
            mensajeError = 'Error al guardar paciente';
        } else {
            mensajeError = 'Error al guardar paciente';
        }
        
        // Mostrar mensaje en la interfaz
        mostrarMensaje(mensajeError, 'error');
        throw error;
    }
}

// Guardar formulario
async function guardarFormulario() {
    console.log('Iniciando guardarFormulario...');
    
    // Verificar si es una actualización y mostrar confirmación
    const btnGuardar = document.getElementById('btn-guardar');
    const esActualizacion = btnGuardar && btnGuardar.getAttribute('data-es-actualizacion') === 'true';
    const formularioId = obtenerValorInput('formulario_id');
    
    if (esActualizacion || formularioId) {
        const confirmar = confirm('¿En verdad desea modificar la información?');
        if (!confirmar) {
            console.log('Actualización cancelada por el usuario');
            return;
        }
    }
    
    try {
        console.log('Guardando paciente...');
        // Primero guardar/actualizar paciente
        await guardarPaciente();
        
        const pacienteId = obtenerValorInput('paciente_id');
        console.log('Paciente ID después de guardar:', pacienteId);
        if (!pacienteId) {
            console.error('No se pudo obtener el ID del paciente');
            mostrarMensaje('Complete los campos del paciente', 'error');
            return;
        }
        
        console.log('Preparando datos del formulario...');
        
        // Preparar datos del formulario
        console.log('Obteniendo valores de los campos...');

        // Campo CÓDIGO ahora es visual/estático en el encabezado.
        // Si no hay input o viene vacío, usamos el código fijo del formato: FRSPA-022
        const codigo = obtenerValorInput('codigo') || 'FRSPA-022';
        // "version" puede no existir en UI (campo ocultado/retirado).
        // Mantener compatibilidad enviando una versión por defecto.
        const version = obtenerValorInput('version') || '1';
        const estado = obtenerValorInput('estado');
        const responsable = obtenerValorInput('responsable');
        
        // Validar campos requeridos
        // Nota: CÓDIGO ya se fuerza a un valor por defecto (FRSPA-022), por eso
        // solo validamos estado y responsable; versión usa fallback "1".
        if (!estado || !responsable) {
            const camposFaltantes = [];
            const idsFaltantes = [];
            if (!estado) { camposFaltantes.push('Estado'); idsFaltantes.push('estado'); }
            if (!responsable) { camposFaltantes.push('Responsable'); idsFaltantes.push('responsable'); }

            const errorMessage = `Campos requeridos faltantes: ${camposFaltantes.join(', ')}`;
            mostrarMensaje(`Complete el/los campo(s) requerido(s): ${camposFaltantes.join(', ')}`, 'error');
            resaltarCamposFaltantes(idsFaltantes);
            throw new Error(errorMessage);
        }
        
        // Obtener edad_snapshot - verificar si tiene valor (incluyendo 0)
        const edadSnapshotInput = document.getElementById('edad_snapshot');
        const edadSnapshotValue = edadSnapshotInput?.value?.trim();
        const edadSnapshot = (edadSnapshotValue !== '' && edadSnapshotValue !== undefined && edadSnapshotValue !== null) ? 
                            parseInt(edadSnapshotValue) : null;
        console.log('🔍 edad_snapshot - Input value:', edadSnapshotValue, 'Parsed:', edadSnapshot);
        
        // Obtener edad_gestion - verificar si tiene valor (incluyendo 0)
        const edadGestionInput = document.getElementById('edad_gestion');
        const edadGestionValue = edadGestionInput?.value?.trim();
        const edadGestion = (edadGestionValue !== '' && edadGestionValue !== undefined && edadGestionValue !== null) ? 
                           parseInt(edadGestionValue) : null;
        
        // Obtener n_controles_prenatales - verificar si tiene valor (incluyendo 0)
        const nControlesInput = document.getElementById('n_controles_prenatales');
        const nControlesValue = nControlesInput?.value?.trim();
        const nControles = (nControlesValue !== '' && nControlesValue !== undefined && nControlesValue !== null) ?
                          parseInt(nControlesValue) : null;

        // Antecedentes obstétricos G/P/C/A - verificar valor (incluyendo 0)
        const parseIntOrNull = (id) => {
            const val = document.getElementById(id)?.value?.trim();
            return (val !== '' && val !== undefined && val !== null) ? parseInt(val) : null;
        };
        const gestas = parseIntOrNull('gestas');
        const partos = parseIntOrNull('partos');
        const cesareas = parseIntOrNull('cesareas');
        const abortos = parseIntOrNull('abortos');

        const formularioData = {
            codigo: codigo,
            version: version,
            fecha_elabora: obtenerValorInput('fecha_elabora') || obtenerFechaLocalColombia(),
            num_hoja: parseInt(obtenerValorInput('num_hoja') || '1'),
            paciente: pacienteId,
            aseguradora_nombre: (obtenerValorInput('aseguradora_nombre') || '').trim(),
            diagnostico: obtenerValorInput('diagnostico') || null,
            edad_snapshot: edadSnapshot,
            edad_gestion: edadGestion,
            estado: estado,
            n_controles_prenatales: nControles,
            gestas: gestas,
            partos: partos,
            cesareas: cesareas,
            abortos: abortos,
            responsable: responsable,
        };
        
        console.log('Datos del formulario preparados:', formularioData);
        
        let formulario;
        
        if (formularioId) {
            console.log('Actualizando formulario existente con ID:', formularioId);
            // Actualizar formulario existente
            formulario = await apiRequest(`/formularios/${formularioId}/`, 'PUT', formularioData);
        } else {
            console.log('Creando nuevo formulario...');
            // Crear nuevo formulario
            formulario = await apiRequest('/formularios/', 'POST', formularioData);
            console.log('Formulario creado:', formulario);
            if (formulario && formulario.id) {
                setValorInput('formulario_id', formulario.id);
            }
        }
        if (!formulario || !formulario.id) {
            console.error('Formulario no creado correctamente:', formulario);
            throw new Error('Formulario no creado correctamente');
        }
        
        console.log('Guardando mediciones para formulario ID:', formulario.id);
        // Guardar mediciones
        await guardarMediciones(formulario.id);
        console.log('Mediciones guardadas exitosamente');

        // Vincular biometría (huella/firma) al formulario actual
        try {
            console.log('Vinculando biometría al formulario...');
            const vincularRes = await fetch(`${API_BASE_URL}/vincular-huella/`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    paciente_id: pacienteId,
                    formulario_id: formulario.id
                })
            });
            if (vincularRes.ok) console.log('✅ Biometría vinculada correctamente');
        } catch (vincularError) {
            console.warn('No se pudo vincular la biometría:', vincularError);
        }
        
        // Actualizar el ID del formulario en el campo oculto
        setValorInput('formulario_id', formulario.id);
        
        // Actualizar el formulario informativo con los datos guardados
        // Esto asegura que el acordeón muestre los datos más recientes
        try {
            await actualizarFormularioInformativo(formulario.id);
            console.log('Formulario informativo actualizado correctamente');
        } catch (error) {
            console.error('Error al actualizar formulario informativo:', error);
            // No fallar el guardado si hay error en la actualización del informativo
        }
        
        const mensaje = esActualizacion ? 'Datos actualizados correctamente' : 'Datos guardados correctamente';
        mostrarMensaje(mensaje, 'success');
        
        // Limpiar el formulario después de un breve delay para que vean el mensaje
        // Nota: El formulario informativo (acordeón) NO se limpia, solo el formulario principal
        setTimeout(() => {
            limpiarFormulario();
            console.log('Formulario reseteado tras guardado exitoso.');
        }, 1500);
        
    } catch (error) {
        console.error('Error al guardar formulario:', error);

        // Los casos de "campos faltantes" (paciente, o Estado/Responsable más arriba)
        // ya muestran su propio mensaje con el nombre del campo y lo resaltan en
        // pantalla; aquí solo cubrimos errores inesperados para no pisar ese mensaje
        // con uno genérico que no dice qué falta diligenciar.
        const esCampoFaltante = error.message.includes('Campos requeridos faltantes') ||
            error.message.includes('Campos de paciente requeridos faltantes');
        if (!esCampoFaltante) {
            mostrarMensaje('Error al guardar formulario', 'error');
        }
    }
}

/**
 * Crea una card de medición para mostrar en la vista previa horizontal.
 * Corregido para mostrar TODOS los parámetros y usar los estilos premium.
 */
function normalizarTextoVistaPrevia(valor) {
    if (valor === null || valor === undefined) return '';
    let text = String(valor);
    try {
        text = decodeURIComponent(escape(text));
    } catch (e) {
        // Mantener texto original cuando no aplica transcodificación.
    }
    return text
        .replace(/Ý/g, 'í')
        .replace(/ß/g, 'á')
        .replace(/¾/g, 'ó')
        .replace(/·/g, 'ú')
        .replace(/Ð/g, 'Ñ')
        .replace(/`/g, "'");
}

/**
 * Construye la tabla de Vista Previa con la misma jerarquía Item -> Parámetro
 * x Hora que usa el PDF oficial (FRSPA-022): una fila por parámetro agrupada
 * bajo su ítem, una columna por cada hora de medición registrada. La lista de
 * items/parámetros activos se lee de window.ESTRUCTURA_ITEMS (inyectada desde
 * el servidor vía json_script), así nunca queda desactualizada respecto a los
 * parámetros realmente disponibles en el formulario.
 */
function construirGrillaVistaPrevia(mediciones, horasUnicas) {
    const estructura = window.ESTRUCTURA_ITEMS || [];
    if (!estructura.length) {
        return `
            <div id="preview-empty-state" class="preview-empty-state">
                <span class="preview-empty-icon">📋</span>
                <p class="preview-empty-text">No hay parámetros configurados para este formulario.</p>
            </div>`;
    }

    // Indexar valores por "parametro_id|hora" -> texto ya combinado (ej. "120 / 80")
    const valoresPorParamHora = {};
    mediciones.forEach(m => {
        const pid = parseInt(m.parametro_id || (m.parametro && m.parametro.id) || m.parametro);
        if (isNaN(pid)) return;
        const key = `${pid}|${m.tomada_en}`;

        const textos = (m.valores || []).map(v => {
            let valor = null;
            if (v.valor_text !== null && v.valor_text !== undefined) valor = v.valor_text;
            else if (v.valor_number !== null && v.valor_number !== undefined) valor = v.valor_number.toString();
            else if (v.valor_boolean !== null && v.valor_boolean !== undefined) valor = v.valor_boolean ? 'SÍ' : 'NO';
            return valor !== null ? normalizarTextoVistaPrevia(valor) : null;
        }).filter(v => v !== null && v !== '');

        if (textos.length) {
            valoresPorParamHora[key] = textos.join(' / ');
        }
    });

    // Encabezado: Ítem | Parámetro | una columna por hora
    let html = '<table class="preview-grid-table"><thead><tr>';
    html += '<th class="preview-grid-th-item" rowspan="2">Ítem</th>';
    html += '<th class="preview-grid-th-param" rowspan="2">Parámetro</th>';
    html += `<th class="preview-grid-th-hora" colspan="${horasUnicas.length}">Hora</th>`;
    html += '</tr><tr>';
    horasUnicas.forEach(hora => {
        const d = new Date(hora);
        const fecha = d.toLocaleDateString('es-ES', { day: '2-digit', month: '2-digit' });
        const horaTxt = d.toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit', hour12: true });
        html += `<th class="preview-grid-th-hora"><span class="preview-grid-col-fecha">${fecha}</span><span class="preview-grid-col-hora">${horaTxt}</span></th>`;
    });
    html += '</tr></thead><tbody>';

    // Filas: un ítem (con rowspan) por cada uno de sus parámetros activos
    estructura.forEach(item => {
        item.parametros.forEach((param, idx) => {
            html += '<tr>';
            if (idx === 0) {
                html += `<td class="preview-grid-td-item" rowspan="${item.parametros.length}">${item.nombre}</td>`;
            }
            const unidad = param.unidad ? ` <span style="opacity:.6;font-weight:600;">(${param.unidad})</span>` : '';
            html += `<td class="preview-grid-td-param">${param.nombre}${unidad}</td>`;

            horasUnicas.forEach(hora => {
                const valor = valoresPorParamHora[`${param.id}|${hora}`];
                html += `<td class="preview-grid-td-valor${valor ? ' tiene-valor' : ''}">${valor || '—'}</td>`;
            });

            html += '</tr>';
        });
    });

    html += '</tbody></table>';
    return html;
}

/**
 * Limpia y oculta la vista previa del paciente.
 */
function limpiarFormularioInformativo() {
    const previewContainer = document.getElementById('vista-previa-paciente');
    if (previewContainer) {
        previewContainer.style.display = 'none';
    }
    const btnPdf = document.getElementById('btn-descargar-pdf');
    if (btnPdf) {
        btnPdf.style.display = 'none';
    }
    const medicionesScroll = document.getElementById('preview-mediciones-scroll');
    if (medicionesScroll) {
        medicionesScroll.innerHTML = '';
    }
}


// Función para actualizar el formulario informativo (Vista Previa) con los datos guardados
// Ahora usa la nueva interfaz premium "card-preview"
async function actualizarFormularioInformativo(formularioId, datosCompletos = null) {
    try {
        console.log(`🚀 Actualizando Dashboard de Vista Previa para el formulario ${formularioId}...`);
        
        let formulario, mediciones, paciente;

        

        if (datosCompletos) {
            formulario = datosCompletos.formulario;
            mediciones = datosCompletos.mediciones || [];
            paciente = datosCompletos.paciente;
        } else {
            const timestamp = new Date().getTime();
            formulario = await apiRequest(`/formularios/${formularioId}/?_=${timestamp}`);
            if (!formulario) return;
            
            mediciones = await apiRequest(`/formularios/${formularioId}/mediciones/?_=${timestamp}`);
            
            const pacienteId = formulario.paciente ? (formulario.paciente.id || formulario.paciente) : null;
            if (pacienteId) {
                paciente = await apiRequest(`/pacientes/${pacienteId}/?_=${timestamp}`);
                
                // Cargar biometría
                try {
                    const huellaData = await apiRequest(`/huella/${pacienteId}/?_=${timestamp}`);
                    if (huellaData && typeof actualizarUIHuella === 'function') {
                        actualizarUIHuella(huellaData);
                    }
                } catch (e) {
                    console.warn('No se pudo cargar biometría para el dashboard:', e);
                }
            }
        }
        
        // Mostrar el contenedor de vista previa
        const previewContainer = document.getElementById('vista-previa-paciente');
        if (previewContainer) previewContainer.style.display = 'block';

        // Mostrar botón de PDF si existe formulario
        const btnPdf = document.getElementById('btn-descargar-pdf');
        if (btnPdf && formularioId) {
            btnPdf.style.display = 'inline-block';
        }

        // 1. Actualizar Datos Personales
        if (paciente) {
            const nombreDisplay = document.getElementById('preview-nombre-display');
            if (nombreDisplay) nombreDisplay.textContent = (paciente.nombres || 'SIN NOMBRE').toUpperCase();
            
            const identDisplay = document.getElementById('preview-identificacion-display');
            if (identDisplay) identDisplay.textContent = paciente.num_identificacion || '-';
            
            const aseguradoraDisplay = document.getElementById('preview-aseguradora');
            if (aseguradoraDisplay) aseguradoraDisplay.textContent = (formulario.aseguradora_nombre || (formulario.aseguradora ? formulario.aseguradora.nombre : (paciente.aseguradora || '-')));
            
            const historiaDisplay = document.getElementById('preview-historia');
            if (historiaDisplay) historiaDisplay.textContent = paciente.num_historia_clinica || '-';
            
            let edad = formulario.edad_snapshot;
            if (!edad && paciente.fecha_nacimiento) edad = calcularEdad(paciente.fecha_nacimiento);
            const edadDisplay = document.getElementById('preview-edad');
            if (edadDisplay) edadDisplay.textContent = edad || '-';
            
            const sangreDisplay = document.getElementById('preview-sangre');
            if (sangreDisplay) sangreDisplay.textContent = paciente.tipo_sangre || '-';
            
            const controlesDisplay = document.getElementById('preview-controles');
            if (controlesDisplay) controlesDisplay.textContent = formulario.n_controles_prenatales || '0';
            
            const gestionDisplay = document.getElementById('preview-gestion');
            if (gestionDisplay) gestionDisplay.textContent = formulario.edad_gestion || '-';

            // Antecedentes
            const setPreview = (id, val) => {
                const el = document.getElementById(id);
                if (el) el.textContent = (val !== null && val !== undefined) ? val : '-';
            };
            setPreview('preview-g', paciente.g);
            setPreview('preview-p', paciente.p);
            setPreview('preview-c', paciente.c);
            setPreview('preview-a', paciente.a);
            setPreview('preview-v', paciente.v);
        }

        const respDisplay = document.getElementById('preview-responsable');
        if (respDisplay && formulario.responsable) {
            respDisplay.textContent = formulario.responsable.toUpperCase();
        }

        // 2. Actualizar Dashboard de Mediciones
        const medicionesScroll = document.getElementById('preview-mediciones-scroll');
        if (medicionesScroll) {
            if (mediciones && mediciones.length > 0) {
                // Identificar todas las horas únicas y ordenarlas
                const horasUnicas = [...new Set(mediciones.map(m => m.tomada_en))].sort();
                const totalControlesDisplay = document.getElementById('preview-total-controles');
                if (totalControlesDisplay) totalControlesDisplay.textContent = `${horasUnicas.length} REGISTROS`;
                
                // Construir la grilla Item -> Parámetro x Hora (misma estructura que el PDF)
                medicionesScroll.innerHTML = construirGrillaVistaPrevia(mediciones, horasUnicas);

                // Sincronizar también con el grid principal (hidden columns/inputs) si es necesario
                const mainTimeInputs = document.querySelectorAll('.time-input');
                horasUnicas.forEach((hora, index) => {
                    if (index < mainTimeInputs.length) {
                        const date = new Date(hora);
                        const year = date.getFullYear();
                        const month = (date.getMonth() + 1).toString().padStart(2, '0');
                        const day = date.getDate().toString().padStart(2, '0');
                        const hours = date.getHours().toString().padStart(2, '0');
                        const minutes = date.getMinutes().toString().padStart(2, '0');
                        mainTimeInputs[index].value = `${year}-${month}-${day}T${hours}:${minutes}`;
                    }
                });

                mediciones.forEach(medicion => {
                    const horaIndex = horasUnicas.indexOf(medicion.tomada_en);
                    if (horaIndex === -1) return;
                    
                    const parametroId = medicion.parametro ? medicion.parametro.id : null;
                    if (!parametroId) return;
                    
                    medicion.valores.forEach(v => {
                        const campoId = v.campo ? v.campo.id : null;
                        if (!campoId) return;
                        
                        const mainSelector = `.data-input[data-parametro-id="${parametroId}"][data-campo-id="${campoId}"][data-hora-index="${horaIndex}"]`;
                        const input = document.querySelector(mainSelector);
                        
                        let valor = '';
                        if (v.valor_text !== null && v.valor_text !== undefined) valor = v.valor_text;
                        else if (v.valor_number !== null && v.valor_number !== undefined) valor = v.valor_number.toString();
                        else if (v.valor_boolean !== null && v.valor_boolean !== undefined) valor = v.valor_boolean ? 'SÍ' : 'NO';
                        
                        if (input) {
                            input.value = valor;
                            input.dispatchEvent(new Event('change', { bubbles: true }));
                        }
                    });
                });

                if (typeof updateProgressiveColumns === 'function') updateProgressiveColumns();
                
                // Hacer scroll al final para ver lo más reciente
                setTimeout(() => {
                    const liveMedicionesScroll = getLiveElementById('preview-mediciones-scroll');
                    if (!liveMedicionesScroll) return;
                    liveMedicionesScroll.scrollLeft = liveMedicionesScroll.scrollWidth;
                }, 300);

            } else {
                const totalControlesDisplay = document.getElementById('preview-total-controles');
                if (totalControlesDisplay) totalControlesDisplay.textContent = `0 REGISTROS`;
                medicionesScroll.innerHTML = `
                    <div id="preview-empty-state" class="preview-empty-state">
                        <span class="preview-empty-icon">📋</span>
                        <p class="preview-empty-text">No se registran mediciones previas para este paciente todavía.</p>
                        <p class="preview-empty-subtext">Los nuevos registros aparecerán aquí automáticamente.</p>
                    </div>`;
            }
            console.log('✅ Dashboard de Vista Previa actualizado con éxito.');
        }
    } catch (error) {
        console.error('❌ Error al actualizar Dashboard de Vista Previa:', error);
    }
}

/**
 * Abre en una pestaña nueva la cuadrícula de historial clínico MEOWS
 * del paciente actual (identificado por número de documento).
 */
function abrirVistaPreviaMeows() {
    const numIdentificacion = (obtenerValorInput('num_identificacion') || '').trim();
    if (!numIdentificacion) {
        mostrarMensaje('Ingrese el número de identificación del paciente antes de ver el historial MEOWS.', 'warning');
        return;
    }
    window.open(`/meows/historial-doc/${encodeURIComponent(numIdentificacion)}/`, '_blank');
}

/**
 * Abre/actualiza manualmente la vista previa de mediciones.
 */
async function abrirVistaPreviaMediciones() {
    const previewContainer = document.getElementById('vista-previa-paciente');
    const btnPreview = document.getElementById('btn-vista-previa');

    // Si ya está visible, ocultar (toggle).
    if (previewContainer && previewContainer.style.display !== 'none' && previewContainer.style.display !== '') {
        previewContainer.style.display = 'none';
        if (btnPreview) btnPreview.textContent = 'Vista Previa';
        return;
    }

    const formularioId = obtenerValorInput('formulario_id');
    if (!formularioId) {
        mostrarMensaje('Primero guarde el formulario para ver la vista previa de mediciones.', 'warning');
        return;
    }

    await actualizarFormularioInformativo(formularioId);

    if (previewContainer) {
        previewContainer.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
    if (btnPreview) btnPreview.textContent = 'Ocultar Vista Previa';
}
        

// Guardar mediciones con envío anidado
/**
 * Guarda TODAS las mediciones pendientes para la hora seleccionada actualmente.
 * Botón Universal para agilizar el registro.
 */
async function guardarTodoElControl() {
    const timeInput = getLiveElementById('hora_registro_actual');
    if (!timeInput || !timeInput.value) {
        mostrarMensaje('Debe fijar la "Hora del Control Actual" antes de guardar', 'error');
        if(timeInput) timeInput.focus();
        return;
    }

    const horaRegistro = obtenerValorInput('hora_registro_actual');
    const medicionesAGuardar = window.medicionesPendientes.filter(m => m.hora === horaRegistro);

    if (medicionesAGuardar.length === 0) {
        mostrarMensaje('No hay nuevos datos registrados para guardar en esta hora', 'warning');
        return;
    }

    const btnSave = getLiveElementById('btn-guardar-todo');
    const originalContent = btnSave ? btnSave.innerHTML : '';
    
    if (btnSave) {
        btnSave.disabled = true;
        btnSave.innerHTML = '<div class="spinner-border spinner-border-sm" role="status"></div> GUARDANDO...';
    }

    try {
        // Asegurar paciente y formulario base
        await guardarPaciente();
        
        const pacienteId = obtenerValorInput('paciente_id');
        let formularioId = obtenerValorInput('formulario_id');

        // Si no hay formulario, creamos uno base con los datos disponibles
        if (!formularioId) {
            console.log('Creando formulario base para las mediciones...');
            const codigo = obtenerValorInput('codigo') || 'FRSPA-022';
            
            const formularioData = {
                codigo: codigo,
                version: obtenerValorInput('version') || '1',
                fecha_elabora: obtenerValorInput('fecha_elabora') || obtenerFechaLocalColombia(),
                num_hoja: parseInt(obtenerValorInput('num_hoja') || '1'),
                paciente: pacienteId,
                aseguradora_nombre: (obtenerValorInput('aseguradora_nombre') || '').trim(),
                diagnostico: obtenerValorInput('diagnostico') || null,
                estado: obtenerValorInput('estado') || 'ACTIVO',
                responsable: obtenerValorInput('responsable') || 'SISTEMA'
            };
            
            const formulario = await apiRequest('/formularios/', 'POST', formularioData);
            if (formulario && formulario.id) {
                formularioId = formulario.id;
                setValorInput('formulario_id', formularioId);
            }
        }

        if (!formularioId) throw new Error('No se pudo establecer un ID de formulario para el guardado');

        // Agrupar mediciones por parámetro
        const medicionesMap = new Map();
        medicionesAGuardar.forEach(med => {
            const key = `${med.parametro_id}`;
            if (!medicionesMap.has(key)) {
                medicionesMap.set(key, {
                    formulario: formularioId,
                    parametro: parseInt(med.parametro_id),
                    tomada_en: new Date(med.hora).toISOString(),
                    valores: []
                });
            }
            const payloadValor = { campo_id: parseInt(med.campo_id) };
            if (med.tipo_valor === 'boolean') {
                const v = (med.valor || "").toString().toUpperCase().trim();
                payloadValor.valor_boolean = v.startsWith('SÍ') || v.startsWith('SI');
            } else if (med.valor !== "" && !isNaN(med.valor) && typeof med.valor !== 'boolean') {
                payloadValor.valor_number = parseFloat(med.valor);
            } else {
                payloadValor.valor_text = med.valor;
            }
            medicionesMap.get(key).valores.push(payloadValor);
        });

        const promesas = Array.from(medicionesMap.values()).map(data => 
            apiRequest('/mediciones/', 'POST', data)
        );

        await Promise.all(promesas);

        // Sincronizar con lo que el backend realmente guardó (en vez de solo
        // vaciar el arreglo local), para que los botones sigan mostrando el
        // valor guardado y el modal se pueda reabrir para corregir un error
        // de digitación en lugar de aparecer vacío.
        await sincronizarMedicionesGuardadas(formularioId, horaRegistro);

        // Actualizar UI de todos los botones (incluye los que quedaron sin
        // dato pendiente, si el usuario borró un valor antes de guardar).
        document.querySelectorAll('.btn-parametro').forEach(btn => {
            const id = btn.getAttribute('data-parametro-id');
            if (id) actualizarBotonUI(id);
        });

        const horaFormateada = new Date(horaRegistro).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        mostrarMensaje(`✅ ¡Los datos de las ${horaFormateada} se han guardado con éxito!`, 'success');
        
        // Actualizar vista informativa
        await actualizarFormularioInformativo(formularioId);

    } catch (error) {
        console.error('Error al guardar todo el control:', error);
        mostrarMensaje('Error al guardar: ' + error.message, 'error');
    } finally {
        const liveBtnSave = getLiveElementById('btn-guardar-todo');
        if (liveBtnSave) {
            liveBtnSave.disabled = false;
            liveBtnSave.innerHTML = originalContent;
        }
    }
}

/**
 * Refresca window.medicionesPendientes con lo que el backend realmente tiene
 * guardado para una hora dada, en vez de solo vaciar el arreglo local tras
 * guardar. El backend ya es "edit-safe" (get_or_create/update_or_create por
 * formulario+parámetro+hora en MedicionCreateSerializer), así que guardar de
 * nuevo sobrescribe en vez de duplicar — lo que faltaba era que el frontend
 * reflejara ese valor guardado para poder verlo y corregirlo, en lugar de
 * dejar el botón/modal en blanco después de guardar o al recargar la página.
 */
async function sincronizarMedicionesGuardadas(formularioId, horaRegistro) {
    if (!formularioId || !horaRegistro) return;
    try {
        const timestamp = new Date().getTime();
        const mediciones = await apiRequest(`/formularios/${formularioId}/mediciones/?_=${timestamp}`);
        if (!Array.isArray(mediciones)) return;

        const formatearComoInputHora = (isoString) => {
            const d = new Date(isoString);
            const y = d.getFullYear();
            const mo = (d.getMonth() + 1).toString().padStart(2, '0');
            const da = d.getDate().toString().padStart(2, '0');
            const h = d.getHours().toString().padStart(2, '0');
            const mi = d.getMinutes().toString().padStart(2, '0');
            return `${y}-${mo}-${da}T${h}:${mi}`;
        };

        const parametrosActualizados = new Set();

        mediciones.forEach(medicion => {
            if (formatearComoInputHora(medicion.tomada_en) !== horaRegistro) return;
            const parametroId = medicion.parametro ? medicion.parametro.id : medicion.parametro;
            if (!parametroId) return;

            (medicion.valores || []).forEach(v => {
                const campoId = v.campo ? v.campo.id : v.campo;
                if (!campoId) return;

                let valor = '';
                let tipoValor;
                if (v.valor_boolean !== null && v.valor_boolean !== undefined) {
                    valor = v.valor_boolean ? 'SÍ' : 'NO';
                    tipoValor = 'boolean';
                } else if (v.valor_text !== null && v.valor_text !== undefined) {
                    valor = v.valor_text;
                } else if (v.valor_number !== null && v.valor_number !== undefined) {
                    valor = v.valor_number.toString();
                }

                const nuevaMedicion = {
                    parametro_id: parametroId,
                    campo_id: campoId,
                    tipo_valor: tipoValor,
                    valor: valor,
                    valor_texto: valor,
                    hora: horaRegistro
                };
                const indiceExistente = window.medicionesPendientes.findIndex(m =>
                    m.parametro_id == parametroId && m.campo_id == campoId && m.hora == horaRegistro
                );
                if (indiceExistente >= 0) {
                    window.medicionesPendientes[indiceExistente] = nuevaMedicion;
                } else {
                    window.medicionesPendientes.push(nuevaMedicion);
                }
                parametrosActualizados.add(String(parametroId));
            });
        });

        parametrosActualizados.forEach(id => actualizarBotonUI(id));
    } catch (e) {
        console.warn('No se pudo sincronizar mediciones guardadas para permitir su edición:', e);
    }
}

// Variable global para almacenar las mediciones que se van a guardar
window.medicionesPendientes = [];

/**
 * Mapa global: { [parametro_id]: { [campo_codigo]: campo_id } }
 * Cargado desde la API al inicio para resolver campo_id cuando no está en el HTML.
 */
window.paramCamposMap = {};

/**
 * Carga el mapa de parámetros→campos desde la API.
 * Se llama una sola vez al cargar la página.
 */
async function loadParamCamposMap() {
    try {
        console.log('🔄 Cargando mapa de campos desde /api/campos-parametro/...');
        const response = await apiRequest('/campos-parametro/');
        // DRF puede devolver el array directo o dentro de .results
        const campos = Array.isArray(response) ? response : (response?.results || []);
        
        // Reset del mapa
        window.paramCamposMap = {};
        
        campos.forEach(campo => {
            const param = campo.parametro;
            if (!param) return;
            
            const paramId = (typeof param === 'object') ? param.id : param;
            if (!window.paramCamposMap[paramId]) {
                window.paramCamposMap[paramId] = {};
            }
            
            // Indexar por código (mayúsculas y minúsculas para robustez)
            if (campo.codigo) {
                const code = campo.codigo.toLowerCase();
                window.paramCamposMap[paramId][code] = campo.id;
                // Si el código es 'VALOR', también registrarlo como clave por defecto
                if (code === 'valor') window.paramCamposMap[paramId]['valor'] = campo.id;
            }
            
            // Indexar también por nombre por si acaso
            if (campo.nombre) {
                window.paramCamposMap[paramId][campo.nombre.toLowerCase()] = campo.id;
            }
        });
        
        console.log('✅ Mapa de campos cargado exitosamente:', window.paramCamposMap);
    } catch (e) {
        console.warn('⚠️ No se pudo cargar el mapa de campos:', e);
    }
}

/**
 * Resuelve el campo_id dado el parametro_id y el campo_codigo.
 * Si ya hay campo_id definido, lo usa directamente.
 */
function resolverCampoId(parametroId, campoId, campoCodigo) {
    if (campoId && campoId !== 'null' && campoId !== 'undefined') return parseInt(campoId);
    
    const pid = parseInt(parametroId);
    const mapa = window.paramCamposMap[pid] || {};
    
    // Intentar por código (en minúsculas por consistencia con loadParamCamposMap)
    const code = (campoCodigo || 'valor').toLowerCase();
    if (mapa[code] !== undefined) return mapa[code];
    
    // Fallback: tomar el primer campo disponible si no se encuentra por código
    const valores = Object.values(mapa);
    if (valores.length > 0) return valores[0];

    // Fallbacks defensivos para parámetros críticos automáticos.
    if (pid === 14) return 18; // Hora Ruptura -> campo TIEMPO
    if (pid === 17) return 19; // Monitoreo Hora -> campo TIEMPO
    
    return null;
}

function obtenerFechaHoraLocalInput() {
    const ahora = new Date();
    const año = ahora.getFullYear();
    const mes = String(ahora.getMonth() + 1).padStart(2, '0');
    const dia = String(ahora.getDate()).padStart(2, '0');
    const horas = String(ahora.getHours()).padStart(2, '0');
    const minutos = String(ahora.getMinutes()).padStart(2, '0');
    return `${año}-${mes}-${dia}T${horas}:${minutos}`;
}

function inicializarHoraRegistroAutomatica() {
    const timeInput = getLiveElementById('hora_registro_actual');
    if (!timeInput) return;
    // Es un campo informativo: se fija con la hora real del sistema y solo
    // puede actualizarse presionando el botón "Ahora" (no se edita a mano).
    timeInput.value = obtenerFechaHoraLocalInput();
    timeInput.readOnly = true;
}


function establecerHoraActual() {
    const timeInput = getLiveElementById('hora_registro_actual');
    if (!timeInput) return;
    timeInput.value = obtenerFechaHoraLocalInput();
    const feedback = document.getElementById('hora-seleccionada-feedback');
    if (feedback) {
        feedback.style.display = 'inline';
        setTimeout(() => { feedback.style.display = 'none'; }, 2000);
    }
    // El campo es de solo lectura (no dispara 'change' al fijarse por JS),
    // así que refrescamos manualmente el estado de los botones de parámetro.
    document.querySelectorAll('.btn-parametro').forEach(btn => {
        const id = btn.getAttribute('data-parametro-id');
        if (id) actualizarBotonUI(id);
    });
}

function abrirModalParametro(button) {
    const timeInput = getLiveElementById('hora_registro_actual');
    if (!timeInput || !timeInput.value) {
        inicializarHoraRegistroAutomatica();
    }
    if (!timeInput || !timeInput.value) {
        mostrarMensaje('No se pudo establecer la hora del control actual', 'warning');
        if(timeInput) timeInput.focus();
        return;
    }
    const parametroId = button.getAttribute('data-parametro-id');
    const modal = document.getElementById(`modal-parametro-${parametroId}`);
    if (modal) {
        modal.style.display = 'flex';
        const horaRegistro = timeInput.value;
        const esParametroHoraMonitoreo = String(parametroId) === '17';
        // Limpiar intervalo previo para evitar múltiples timers abiertos.
        if (window._autoHoraModal17Interval) {
            clearInterval(window._autoHoraModal17Interval);
            window._autoHoraModal17Interval = null;
        }
        
        // Pre-llenar con datos pendientes si existen para esta hora
        modal.querySelectorAll('.data-input-modal').forEach(input => {
            const campoId = input.getAttribute('data-campo-id');
            const medicion = window.medicionesPendientes.find(m => 
                m.parametro_id == parametroId && 
                m.campo_id == campoId && 
                m.hora == horaRegistro
            );
            // Parametro 14 (HORA RUPTURA): valor automático, no editable.
            if (String(parametroId) === '14') {
                let valorAutomatico = medicion ? medicion.valor : horaRegistro;
                if (input.type === 'time') {
                    const source = horaRegistro || obtenerFechaHoraLocalInput();
                    const hhmm = source.includes('T') ? source.split('T')[1].slice(0, 5) : source.slice(0, 5);
                    valorAutomatico = medicion ? medicion.valor : hhmm;
                }
                input.value = valorAutomatico;
                input.readOnly = true;
                registrarCambioDatoModal(input);
                return;
            }
            // Parámetro 17 (HORA MONITOREO): siempre automático en tiempo real.
            if (esParametroHoraMonitoreo && input.type === 'datetime-local') {
                input.value = obtenerFechaHoraLocalInput();
                input.readOnly = true;
                registrarCambioDatoModal(input);
                return;
            }
            input.readOnly = false;
            input.value = medicion ? medicion.valor : '';
        });

        // Modal de MEMBRANAS (parámetro 11): el campo "Hora de la ruptura" pertenece
        // en realidad al parámetro 14 / campo 18, así que el bucle genérico de arriba
        // (que busca la medición pendiente usando el parametroId del MODAL, no el del
        // propio input) no lo puede pre-llenar correctamente. Se corrige aquí.
        if (String(parametroId) === '11') {
            const selectMembranas = modal.querySelector('#select-membranas');
            const inputHoraRuptura = modal.querySelector('#input-hora-ruptura-membranas');
            if (inputHoraRuptura) {
                const medicionHora = window.medicionesPendientes.find(m =>
                    m.parametro_id == 14 &&
                    m.campo_id == 18 &&
                    m.hora == horaRegistro
                );
                inputHoraRuptura.value = medicionHora ? medicionHora.valor : '';
                restaurarHoraRupturaMembranasDesdeValor(inputHoraRuptura.value);
            }
            if (selectMembranas) {
                toggleHoraRupturaMembranas(selectMembranas);
            }
        }

        // Modal HORA del monitoreo (parámetro 17): selector 12h + AM/PM. El bucle
        // genérico de arriba ya dejó el input oculto con el valor pendiente (si
        // existía, mismo parametroId/campoId); acá se refleja en los 3 selects.
        if (esParametroHoraMonitoreo) {
            const inputHoraMonitoreo = modal.querySelector('#input-hora-monitoreo');
            if (inputHoraMonitoreo && inputHoraMonitoreo.value) {
                restaurarHoraDesdeValor('hora-monitoreo-horas', 'hora-monitoreo-minutos', 'hora-monitoreo-periodo', inputHoraMonitoreo.value);
            } else {
                poblarYPresetSelectHora('hora-monitoreo-horas', 'hora-monitoreo-minutos', 'hora-monitoreo-periodo');
                actualizarHoraMonitoreoSelects();
            }
        }

        // Mantener hora actualizada en tiempo real mientras el modal esté abierto.
        if (esParametroHoraMonitoreo) {
            window._autoHoraModal17Interval = setInterval(() => {
                if (!modal || modal.style.display === 'none') {
                    clearInterval(window._autoHoraModal17Interval);
                    window._autoHoraModal17Interval = null;
                    return;
                }
                const inputHora = modal.querySelector('.data-input-modal[type="datetime-local"]');
                if (inputHora) {
                    inputHora.value = obtenerFechaHoraLocalInput();
                    registrarCambioDatoModal(inputHora);
                }
            }, 1000);
        }
    }
}

/**
 * Convierte una hora en formato 24h "HH:MM" a texto 12h + AM/PM (ej. "14:30" -> "02:30 PM").
 */
function formatearHora12(valorHHMM) {
    if (!valorHHMM || !valorHHMM.includes(':')) return valorHHMM;
    const [hhStr, mm] = valorHHMM.split(':');
    const horas24 = parseInt(hhStr, 10);
    if (isNaN(horas24)) return valorHHMM;
    let horas12 = horas24 % 12;
    if (horas12 === 0) horas12 = 12;
    const periodo = horas24 >= 12 ? 'PM' : 'AM';
    return `${String(horas12).padStart(2, '0')}:${mm} ${periodo}`;
}

/**
 * Actualiza la información visual en el botón del parámetro para mostrar el valor ingresado.
 */
function actualizarBotonUI(parametroId) {
    const btn = document.getElementById(`btn-parametro-${parametroId}`);
    if (!btn) return;

    const valPreview = document.getElementById(`val-preview-${parametroId}`);
    const timeInput = document.getElementById('hora_registro_actual');
    if (!timeInput || !timeInput.value) return;
    const horaRegistro = timeInput.value;

    const mediciones = window.medicionesPendientes.filter(m =>
        m.parametro_id == parametroId && m.hora == horaRegistro
    );

    if (mediciones.length > 0) {
        btn.classList.add('tiene-datos');

        // Unir valores (ej: 120/80). El botón ahora tiene espacio para mostrar
        // el texto completo (con salto de línea si hace falta), sin truncar.
        // Se usa valor_texto (la descripción completa de la opción elegida,
        // ej. "0 Sin dinámica") cuando existe; valor es solo el código guardado.
        let partes = mediciones.map(m => m.valor_texto || m.valor);

        // Botón MEMBRANAS (11): si quedó "Rotas", mostrar también la hora de la
        // ruptura (parámetro 14 / campo 18) junto al valor, en formato 12h.
        if (String(parametroId) === '11' && mediciones.some(m => m.valor === 'Rotas')) {
            const medicionHora = window.medicionesPendientes.find(m =>
                m.parametro_id == 14 && m.campo_id == 18 && m.hora == horaRegistro
            );
            if (medicionHora && medicionHora.valor) {
                partes.push(formatearHora12(medicionHora.valor));
            }
        }

        const valStr = partes.join(' / ');

        if (valPreview) {
            valPreview.textContent = valStr;
            valPreview.style.color = '#047857';
        }
    } else {
        btn.classList.remove('tiene-datos');
        if (valPreview) {
            valPreview.textContent = '-';
            valPreview.style.color = '#94a3b8';
        }
    }
}

/**
 * Para un <select>, input.value solo trae el código guardado (ej. "0"), no la
 * descripción visible (ej. "0 Sin dinámica"). Este helper devuelve el texto
 * completo de la opción elegida para mostrarlo en el botón del parámetro,
 * sin afectar el valor que realmente se guarda/envía al backend.
 */
function obtenerTextoLegibleInput(input) {
    if (input.tagName === 'SELECT') {
        const opt = input.options[input.selectedIndex];
        return opt ? opt.text.trim() : input.value.trim();
    }
    return input.value.trim();
}

/**
 * Captura el cambio en un input de modal y actualiza los pendientes y la UI.
 */
function registrarCambioDatoModal(input) {
    const parametroId = input.getAttribute('data-parametro-id');
    const rawCampoId = input.getAttribute('data-campo-id');
    const campoCodigo = input.getAttribute('data-campo-codigo');
    const tipoValor = input.getAttribute('data-tipo-valor');
    const valor = input.value.trim();
    const valorTexto = obtenerTextoLegibleInput(input);

    // Resolver campo_id usando helper (usa rawCampoId si existe, sino busca en el mapa por campoCodigo)
    const campoId = resolverCampoId(parametroId, rawCampoId, campoCodigo);

    const timeInput = document.getElementById('hora_registro_actual');
    if (!timeInput || !timeInput.value) return;
    const horaRegistro = timeInput.value;

    const indiceExistente = window.medicionesPendientes.findIndex(m => 
        m.parametro_id == parametroId && 
        m.campo_id == campoId && 
        m.hora == horaRegistro
    );

    if (valor) {
        const nuevaMedicion = {
            parametro_id: parametroId,
            campo_id: campoId,
            tipo_valor: tipoValor,
            valor: valor,
            valor_texto: valorTexto,
            hora: horaRegistro
        };

        if (indiceExistente >= 0) {
            window.medicionesPendientes[indiceExistente] = nuevaMedicion;
        } else {
            window.medicionesPendientes.push(nuevaMedicion);
        }
    } else {
        if (indiceExistente >= 0) {
            window.medicionesPendientes.splice(indiceExistente, 1);
        }
    }

    actualizarBotonUI(parametroId);
}

/**
 * Selectores de hora en formato 12h + AM/PM (evitan el <input type="time">
 * nativo, cuyo formato AM/PM depende del idioma del sistema operativo del
 * usuario). Cada uso mantiene sincronizado un input oculto en formato 24h
 * (HH:MM), que es lo que realmente se guarda en medicionesPendientes.
 * Utilidades genéricas (reutilizadas por "Hora de la ruptura" y "Hora" del
 * monitoreo) parametrizadas por los IDs de los 3 selects + el input oculto.
 */
function poblarSelectHoras12(select) {
    if (!select || select.dataset.poblado) return;
    select.dataset.poblado = '1';
    for (let h = 1; h <= 12; h++) {
        const opt = document.createElement('option');
        opt.value = String(h).padStart(2, '0');
        opt.textContent = String(h).padStart(2, '0');
        select.appendChild(opt);
    }
}

function poblarSelectMinutos60(select) {
    if (!select || select.dataset.poblado) return;
    select.dataset.poblado = '1';
    for (let m = 0; m < 60; m++) {
        const opt = document.createElement('option');
        opt.value = String(m).padStart(2, '0');
        opt.textContent = String(m).padStart(2, '0');
        select.appendChild(opt);
    }
}

/**
 * Popula los 3 selects (si hace falta) y, si aún no hay nada elegido,
 * preselecciona la hora actual como punto de partida práctico.
 */
function poblarYPresetSelectHora(idHoras, idMinutos, idPeriodo) {
    const horasSel = document.getElementById(idHoras);
    const minutosSel = document.getElementById(idMinutos);
    const periodoSel = document.getElementById(idPeriodo);
    if (!horasSel || !minutosSel || !periodoSel) return;

    poblarSelectHoras12(horasSel);
    poblarSelectMinutos60(minutosSel);

    if (!horasSel.value || !minutosSel.value) {
        const ahora = new Date();
        const horas24Actual = ahora.getHours();
        let horas12Actual = horas24Actual % 12;
        if (horas12Actual === 0) horas12Actual = 12;
        horasSel.value = String(horas12Actual).padStart(2, '0');
        minutosSel.value = String(ahora.getMinutes()).padStart(2, '0');
        periodoSel.value = horas24Actual >= 12 ? 'PM' : 'AM';
    }
}

/**
 * Calcula el valor 24h (HH:MM) a partir de los 3 selects y lo guarda en el
 * input oculto correspondiente, registrando el cambio.
 */
function actualizarHoraOculta(idHoras, idMinutos, idPeriodo, idOculto) {
    const horasSel = document.getElementById(idHoras);
    const minutosSel = document.getElementById(idMinutos);
    const periodoSel = document.getElementById(idPeriodo);
    const hiddenInput = document.getElementById(idOculto);
    if (!horasSel || !minutosSel || !periodoSel || !hiddenInput) return;

    const horas12 = parseInt(horasSel.value, 10);
    const minutos = minutosSel.value;
    const periodo = periodoSel.value;

    if (isNaN(horas12) || !minutos || !periodo) {
        hiddenInput.value = '';
    } else {
        let horas24 = horas12 % 12;
        if (periodo === 'PM') horas24 += 12;
        hiddenInput.value = `${String(horas24).padStart(2, '0')}:${minutos}`;
    }

    registrarCambioDatoModal(hiddenInput);
}

/**
 * Refleja un valor 24h ("HH:MM") ya guardado en los 3 selects (al reabrir
 * el modal con un dato pendiente previo).
 */
function restaurarHoraDesdeValor(idHoras, idMinutos, idPeriodo, valorHHMM) {
    const horasSel = document.getElementById(idHoras);
    const minutosSel = document.getElementById(idMinutos);
    const periodoSel = document.getElementById(idPeriodo);
    if (!horasSel || !minutosSel || !periodoSel) return;

    poblarSelectHoras12(horasSel);
    poblarSelectMinutos60(minutosSel);

    if (!valorHHMM) return;
    const [hh, mm] = valorHHMM.split(':');
    const horas24 = parseInt(hh, 10);
    if (isNaN(horas24)) return;
    let horas12 = horas24 % 12;
    if (horas12 === 0) horas12 = 12;
    horasSel.value = String(horas12).padStart(2, '0');
    minutosSel.value = mm;
    periodoSel.value = horas24 >= 12 ? 'PM' : 'AM';
}

// --- "Hora de la ruptura" (modal MEMBRANAS, parámetro 14 / campo 18) ---
function actualizarHoraRupturaMembranas() {
    actualizarHoraOculta('hora-ruptura-horas', 'hora-ruptura-minutos', 'hora-ruptura-periodo', 'input-hora-ruptura-membranas');
}

function restaurarHoraRupturaMembranasDesdeValor(valorHHMM) {
    restaurarHoraDesdeValor('hora-ruptura-horas', 'hora-ruptura-minutos', 'hora-ruptura-periodo', valorHHMM);
}

// --- "Hora" del monitoreo (modal parámetro 17 / campo 19) ---
function actualizarHoraMonitoreoSelects() {
    actualizarHoraOculta('hora-monitoreo-horas', 'hora-monitoreo-minutos', 'hora-monitoreo-periodo', 'input-hora-monitoreo');
}

/**
 * Muestra/oculta el campo "Hora de la ruptura" dentro del modal de MEMBRANAS
 * según la opción elegida. Si se oculta, limpia cualquier valor pendiente
 * guardado previamente para no dejar datos huérfanos.
 */
function toggleHoraRupturaMembranas(select) {
    const grupo = document.getElementById('grupo-hora-ruptura-membranas');
    if (!grupo) return;

    if (select.value === 'Rotas') {
        grupo.style.display = 'block';
        poblarYPresetSelectHora('hora-ruptura-horas', 'hora-ruptura-minutos', 'hora-ruptura-periodo');
        actualizarHoraRupturaMembranas();
    } else {
        grupo.style.display = 'none';
        const inputHora = document.getElementById('input-hora-ruptura-membranas');
        if (inputHora && inputHora.value) {
            inputHora.value = '';
            registrarCambioDatoModal(inputHora);
        }
    }
}

function cerrarModalParametro(parametroId) {
    const modal = document.getElementById(`modal-parametro-${parametroId}`);
    if (modal) {
        // Red de seguridad: sincroniza una última vez todos los campos antes de
        // cerrar (cubre el caso de autocompletado del navegador u otros cambios
        // que no hayan disparado 'input'/'change').
        modal.querySelectorAll('.data-input-modal').forEach(input => registrarCambioDatoModal(input));
        actualizarBotonUI(parametroId);
        modal.style.display = 'none';
    }
    if (String(parametroId) === '17' && window._autoHoraModal17Interval) {
        clearInterval(window._autoHoraModal17Interval);
        window._autoHoraModal17Interval = null;
    }
}

function guardarTemporalParametro(parametroId) {
    const modal = document.getElementById(`modal-parametro-${parametroId}`);
    const timeInput = document.getElementById('hora_registro_actual');
    const horaRegistro = timeInput.value;
    
    if (!modal) return;
    
    let tieneValores = false;
    const inputs = modal.querySelectorAll('.data-input-modal');
    
    inputs.forEach(input => {
        const rawCampoId = input.getAttribute('data-campo-id');
        const campoCodigo = input.getAttribute('data-campo-codigo');
        const tipoValor = input.getAttribute('data-tipo-valor');
        const valor = input.value.trim();
        const valorTexto = obtenerTextoLegibleInput(input);

        // Resolver campo_id usando helper
        const campoId = resolverCampoId(parametroId, rawCampoId, campoCodigo);

        if (valor) {
            tieneValores = true;
            const indiceExistente = window.medicionesPendientes.findIndex(m =>
                m.parametro_id == parametroId &&
                m.campo_id == campoId &&
                m.hora == horaRegistro
            );

            const nuevaMedicion = {
                parametro_id: parametroId,
                campo_id: campoId,
                tipo_valor: tipoValor,
                valor: valor,
                valor_texto: valorTexto,
                hora: horaRegistro
            };

            if (indiceExistente >= 0) {
                window.medicionesPendientes[indiceExistente] = nuevaMedicion;
            } else {
                window.medicionesPendientes.push(nuevaMedicion);
            }
        }
    });

    if (tieneValores) {
        const btn = document.getElementById(`btn-parametro-${parametroId}`);
        if (btn) btn.classList.add('tiene-datos');
        actualizarBotonUI(parametroId);
        cerrarModalParametro(parametroId);
        mostrarMensaje('Dato guardado temporalmente. Pulse "Guardar Formulario" al final.', 'success');
    } else {
        mostrarMensaje('No se ingresaron valores', 'warning');
    }
}

async function guardarMediciones(formularioId) {
    const medicionesMap = new Map();
    
    // 1. Extraer horas válidas definidas en el encabezado de la cuadrícula
    const timeInputs = document.querySelectorAll('.time-input');
    const horaMap = {};
    timeInputs.forEach((input, index) => {
        if (input.value) {
            // Asumimos que el input es datetime-local (YYYY-MM-DDTHH:MM)
            horaMap[index] = new Date(input.value).toISOString();
        }
    });

    // 2. Extraer todos los valores digitados en la cuadrícula
    const dataInputs = document.querySelectorAll('.data-input');
    dataInputs.forEach(input => {
        const valor = input.value.trim();
        if (valor === '') return; // Ignorar celdas vacías
        
        const parametroId = input.getAttribute('data-parametro-id');
        const campoId = input.getAttribute('data-campo-id');
        // El atributo puede llamarse data-hora-index dependiendo de cómo fue renderizado
        let horaIndexAttr = input.getAttribute('data-hora-index');
        
        // Si no lo encuentra, a veces index lo manejan implícitamente, pero en la carga usan data-hora-index
        if (horaIndexAttr === null) return;
        
        const horaIndex = parseInt(horaIndexAttr);
        const tipoValor = input.getAttribute('data-tipo-valor') || 'number';
        
        // Si no hay hora definida para esta columna, se omite (notificamos en consola)
        const horaIso = horaMap[horaIndex];
        if (!horaIso) {
            console.warn(`Valor omitido: Hay datos en la columna ${horaIndex + 1} pero no se definió la hora en el encabezado.`);
            return; 
        }

        const key = `${parametroId}-${horaIso}`;
        if (!medicionesMap.has(key)) {
            medicionesMap.set(key, {
                formulario: formularioId,
                parametro: parseInt(parametroId),
                tomada_en: horaIso,
                valores: []
            });
        }
        
        const payloadValor = { campo_id: parseInt(campoId) };
        if (tipoValor === 'number') {
            const numero = parseFloat(valor);
            if (!isNaN(numero)) {
                payloadValor.valor_number = numero;
            } else {
                payloadValor.valor_text = valor;
            }
        } else if (tipoValor === 'text') {
            payloadValor.valor_text = valor;
        } else if (tipoValor === 'boolean') {
            const valorUpper = valor.toUpperCase();
            payloadValor.valor_boolean = valorUpper.startsWith('SÍ') || valorUpper.startsWith('SI');
        } else {
            payloadValor.valor_text = valor;
        }
        
        medicionesMap.get(key).valores.push(payloadValor);
    });

    // 3. Incluir las mediciones que vengan del modal (por si se sigue usando)
    if (window.medicionesPendientes && window.medicionesPendientes.length > 0) {
        window.medicionesPendientes.forEach(med => {
            const horaIso = new Date(med.hora).toISOString();
            const key = `${med.parametro_id}-${horaIso}`;
            
            if (!medicionesMap.has(key)) {
                medicionesMap.set(key, {
                    formulario: formularioId,
                    parametro: parseInt(med.parametro_id),
                    tomada_en: horaIso,
                    valores: []
                });
            }
            
            const payloadValor = { campo_id: parseInt(med.campo_id) };
            if (med.tipo_valor === 'number') {
                const numero = parseFloat(med.valor);
                if (!isNaN(numero)) {
                    payloadValor.valor_number = numero;
                } else {
                    payloadValor.valor_text = med.valor;
                }
            } else if (med.tipo_valor === 'text') {
                payloadValor.valor_text = med.valor;
            } else if (med.tipo_valor === 'boolean') {
                const valorUpper = med.valor.toUpperCase().trim();
                payloadValor.valor_boolean = valorUpper.startsWith('SÍ') || valorUpper.startsWith('SI');
            }
            
            // Evitar duplicados si existe en cuadrícula y modal
            const existingCampoIndex = medicionesMap.get(key).valores.findIndex(v => v.campo_id === payloadValor.campo_id);
            if (existingCampoIndex >= 0) {
                medicionesMap.get(key).valores[existingCampoIndex] = payloadValor; // Sobrescribir con modal
            } else {
                medicionesMap.get(key).valores.push(payloadValor);
            }
        });
    }
    
    // Si no hay nada para guardar, salir temprano
    if (medicionesMap.size === 0) {
        console.log('No hay mediciones en la cuadrícula ni pendientes para guardar.');
        return;
    }

    const promesas = Array.from(medicionesMap.values()).map(data => 
        apiRequest('/mediciones/', 'POST', data)
    );
    
    try {
        await Promise.all(promesas);
        console.log('Todas las mediciones se han procesado exitosamente.');
    } catch (error) {
        console.error('Error al enviar mediciones al backend:', error);
        throw error;
    }
    
    // Limpieza post-guardado
    window.medicionesPendientes = [];
    document.querySelectorAll('.btn-parametro.tiene-datos').forEach(btn => btn.classList.remove('tiene-datos'));
}

// Mostrar mensajes usando Toastify
function mostrarMensaje(mensaje, tipo = 'info') {
    let backgroundColor = "#3b82f6"; // Info (Blue)
    if (tipo === 'success') backgroundColor = "#10b981"; // Success (Green)
    if (tipo === 'error') backgroundColor = "#ef4444"; // Error (Red)
    if (tipo === 'warning') backgroundColor = "#f59e0b"; // Warning (Orange)

    if (typeof Toastify !== 'undefined') {
        Toastify({
            text: mensaje,
            duration: 5000,
            close: true,
            gravity: "top", 
            position: "right", 
            stopOnFocus: true, 
            style: {
                background: backgroundColor,
                borderRadius: "8px",
                fontWeight: "500",
                boxShadow: "0 10px 15px -3px rgba(0, 0, 0, 0.1)"
            }
        }).showToast();
    } else {
        // Fallback si Toastify no carga
        console.log(`[${tipo.toUpperCase()}] ${mensaje}`);
    }
}

// Función para cambiar el texto del botón entre "Guardar" y "Actualizar"
function actualizarTextoBoton(esActualizacion) {
    const btnGuardar = document.getElementById('btn-guardar');
    if (btnGuardar) {
        if (esActualizacion) {
            btnGuardar.textContent = 'Actualizar Formulario';
            btnGuardar.setAttribute('data-es-actualizacion', 'true');
        } else {
            btnGuardar.textContent = 'Guardar Formulario';
            btnGuardar.removeAttribute('data-es-actualizacion');
        }
    }
}

// Función consolidada para buscar paciente completo con formulario y mediciones
// Implementa caché completa de todos los datos del paciente
async function buscarPacienteCompleto(cedula, usarCache = true) {
    try {
        console.log(`Buscando paciente completo para identificación: ${cedula}`);
        
        const cacheKey = 'paciente_completo_data_cache';
        const CACHE_VERSION = 5; // Incrementar si cambia estructura (ej. diagnostico, aseguradora, edad_gestacional, n_controles, estado)
        
        // Verificar si hay datos en caché para este paciente
        if (usarCache) {
            try {
                const cacheData = localStorage.getItem(cacheKey);
                if (cacheData) {
                    const parsedCache = JSON.parse(cacheData);
                    if (parsedCache._cacheVersion !== CACHE_VERSION) {
                        localStorage.removeItem(cacheKey);
                    } else if (parsedCache.paciente && parsedCache.paciente.num_identificacion === cedula) {
                        console.log(`✅ Datos encontrados en caché para paciente: ${cedula}`);
                        console.log('Usando datos de caché (evitando petición HTTP)');
                        if (parsedCache.encontrado === undefined) {
                            parsedCache.encontrado = true;
                        }
                        return parsedCache;
                    } else {
                        // Es un paciente diferente, limpiar caché anterior
                        console.log(`Limpiando caché del paciente anterior (${parsedCache.paciente?.num_identificacion || 'desconocido'})`);
                        localStorage.removeItem(cacheKey);
                    }
                }
            } catch (e) {
                console.warn('Error al leer caché, continuando con petición HTTP:', e);
                localStorage.removeItem(cacheKey);
            }
        }
        
        // Buscar datos del paciente desde la API
        console.log('Realizando petición HTTP al servidor...');
        const data = await apiRequest(`/pacientes/buscar-completo/?num_identificacion=${encodeURIComponent(cedula)}`);
        
        // Verificar si el paciente fue encontrado (nuevo formato sin errores 404)
        if (!data || data.encontrado === false || !data.paciente) {
            console.log('Paciente no encontrado:', data?.mensaje || 'Sin mensaje');
            // Si no se encuentra, limpiar la caché
            localStorage.removeItem(cacheKey);
            return { encontrado: false, mensaje: data?.mensaje || 'Paciente no encontrado' };
        }
        
        // Guardar TODA la data completa en caché
        try {
            const cacheData = {
                _cacheVersion: CACHE_VERSION,
                paciente: data.paciente,
                formulario: data.formulario,
                mediciones: data.mediciones || [],
                huella: data.huella || null,
                num_identificacion: data.paciente.num_identificacion,
                timestamp: new Date().getTime(),
                paciente_id: data.paciente.id
            };
            
            localStorage.setItem(cacheKey, JSON.stringify(cacheData));
            console.log(`✅ Caché guardada completa para paciente: ${data.paciente.num_identificacion}`);
            console.log(`   - Paciente: ${data.paciente.nombres}`);
            console.log(`   - Formulario: ${data.formulario ? 'Sí' : 'No'}`);
            console.log(`   - Mediciones: ${data.mediciones?.length || 0}`);
        } catch (e) {
            console.warn('No se pudo guardar caché completa (datos muy grandes):', e);
            // Si los datos son muy grandes, intentar guardar solo información básica
            try {
                localStorage.setItem('paciente_completo_data_cache', JSON.stringify({
                    _cacheVersion: CACHE_VERSION,
                    paciente: data.paciente,
                    formulario: null,
                    mediciones: [],
                    huella: null,
                    num_identificacion: data.paciente.num_identificacion,
                    timestamp: new Date().getTime(),
                    paciente_id: data.paciente.id,
                    cache_incompleto: true
                }));
                console.log('Caché básica guardada (sin formulario/mediciones por tamaño)');
            } catch (e2) {
                console.error('No se pudo guardar ningún tipo de caché:', e2);
            }
        }
        
        console.log('📦 Datos completos recibidos desde API:', data);
        console.log('📋 Estructura de datos recibidos:');
        console.log('   - encontrado:', data?.encontrado);
        console.log('   - paciente:', data?.paciente ? {
            id: data.paciente.id,
            num_identificacion: data.paciente.num_identificacion,
            nombres: data.paciente.nombres,
            edad_gestacional: data.paciente.edad_gestacional,
            n_controles_prenatales: data.paciente.n_controles_prenatales
        } : 'No disponible');
        console.log('   - formulario:', data?.formulario ? 'Sí' : 'No');
        console.log('   - mediciones:', data?.mediciones?.length || 0);
        return data;
    } catch (error) {
        console.error('Error al buscar paciente completo:', error);
        // En caso de error, limpiar caché
        localStorage.removeItem('paciente_completo_data_cache');
        throw error;
    }
}

/**
 * Llena el formulario con datos de paciente (y formulario si existe).
 * Usa edad_gestacional / n_controles_prenatales de la API cuando vienen en buscar-completo (DGEMPRES03).
 */
async function llenarFormularioDesdePaciente(data) {
    if (!data || !data.paciente) return;
    const p = data.paciente;
    const f = data.formulario || null;

    const set = (id, val) => {
        const el = document.getElementById(id);
        if (el && (val !== undefined && val !== null)) el.value = String(val);
    };

    /** Siempre asigna valor a inputs numéricos; usa '' si no hay dato (incluye 0 como válido). */
    const setNum = (id, val) => {
        const el = document.getElementById(id);
        if (!el) return;
        const ok = val !== undefined && val !== null && val !== '';
        el.value = ok ? String(val) : '';
    };

    set('paciente_id', p.id);
    set('num_historia_clinica', p.num_historia_clinica);
    set('num_identificacion', p.num_identificacion);
    set('nombres', p.nombres);
    set('tipo_sangre', p.tipo_sangre);
    // Distingue "la fuente (historia clínica) no trae este dato" de un valor que el usuario
    // simplemente no ha diligenciado todavía, para que no se confunda con un error de consulta.
    const badgeTipoSangre = document.getElementById('tipo-sangre-sin-dato-badge');
    if (badgeTipoSangre) {
        badgeTipoSangre.style.display = (!p.tipo_sangre) ? 'inline-block' : 'none';
    }

    const fechaElabora = document.getElementById('fecha_elabora_paciente');
    if (fechaElabora) fechaElabora.value = p.fecha_nacimiento || obtenerFechaLocalColombia();

    if (p.fecha_nacimiento && typeof calcularEdad === 'function') {
        const edad = calcularEdad(p.fecha_nacimiento);
        set('edad_snapshot', edad);
    }

    const edadGestion = f?.edad_gestion ?? p.edad_gestacional ?? p.edad_gestion;
    const nControles = f?.n_controles_prenatales ?? p.n_controles_prenatales ?? p.controles_prenatales;
    setNum('edad_gestion', edadGestion);
    setNum('n_controles_prenatales', nControles);
    setNum('controles_prenatales', nControles);
    setNum('gestas', f?.gestas ?? p.g);
    setNum('partos', f?.partos ?? p.p);
    setNum('cesareas', f?.cesareas ?? p.c);
    setNum('abortos', f?.abortos ?? p.a);
    if (typeof console !== 'undefined' && console.log) {
        console.log('📋 [llenarFormulario] edad_gestion:', edadGestion, 'n_controles_prenatales:', nControles,
            '| paciente:', { edad_gestacional: p.edad_gestacional, edad_gestion: p.edad_gestion, n_controles_prenatales: p.n_controles_prenatales, controles_prenatales: p.controles_prenatales },
            '| formulario:', f ? { edad_gestion: f.edad_gestion, n_controles_prenatales: f.n_controles_prenatales } : 'N/A');
    }

    if (document.getElementById('edad_gestacional')) set('edad_gestacional', p.edad_gestacional ?? edadGestion);
    if (document.getElementById('controles_prenatales')) set('controles_prenatales', nControles);

    if (f) {
        set('formulario_id', f.id);
        set('codigo', f.codigo);
        set('num_hoja', f.num_hoja);
        const estadoFormulario = (f.estado || '').toString().toLowerCase();
        set('estado', estadoFormulario || 'g');
        set('diagnostico', f.diagnostico || p.diagnostico || '');
        set('responsable', f.responsable || p.responsable || '');
        const ase = document.getElementById('aseguradora_nombre');
        // El formulario propio manda si ya tiene aseguradora asignada; si no, se refleja
        // la del HUB (meows.Paciente) para no dejar el campo vacío teniendo el dato disponible.
        if (ase) {
            if (f.aseguradora && f.aseguradora.nombre) ase.value = f.aseguradora.nombre;
            else if (p.aseguradora || p.aseguradora_nombre) ase.value = p.aseguradora || p.aseguradora_nombre || '';
        }
        
        // Cargar vista informativa con los datos consolidados si existen mediciones
        if (typeof actualizarFormularioInformativo === 'function' && data.mediciones) {
            await actualizarFormularioInformativo(f.id, data);
        }
    } else {
        // Limpiar la vista informativa si el paciente no tiene formulario
        if (typeof limpiarFormularioInformativo === 'function') {
            limpiarFormularioInformativo();
        }
        
        if (p.diagnostico) set('diagnostico', p.diagnostico);
        const estadoPaciente = (p.estado || '').toString().toLowerCase();
        set('estado', estadoPaciente || 'g');
        const ase = document.getElementById('aseguradora_nombre');
        if (ase && (p.aseguradora || p.aseguradora_nombre)) {
            ase.value = p.aseguradora || p.aseguradora_nombre || '';
        }
    }

    // Actualizar sección de biometría si existe data
    if (data.huella && typeof actualizarUIHuella === 'function') {
        console.log('🔐 Cargando biometría guardada en la interfaz...');
        actualizarUIHuella(data.huella);
    } else {
        // Limpiar UI de biometría si no hay datos
        const imgH = document.getElementById('imgHuella');
        const imgF = document.getElementById('imgFirma');
        if (imgH) { imgH.src = ''; imgH.style.display = 'none'; }
        if (imgF) { imgF.src = ''; imgF.style.display = 'none'; }
        const estH = document.getElementById('estadoHuella');
        const estF = document.getElementById('estadoFirma');
        if (estH) { estH.innerHTML = 'No capturada'; estH.style.display = 'block'; }
        if (estF) { estF.innerHTML = 'No capturada'; estF.style.display = 'block'; }
    }

    // Estos campos ya vinieron resueltos desde la historia clínica del paciente:
    // son informativos, no se editan aquí una vez identificado el paciente.
    bloquearCamposIdentificacionPaciente();
}

function bloquearCamposIdentificacionPaciente() {
    ['fecha_elabora_paciente', 'num_identificacion', 'num_historia_clinica', 'nombres',
     'edad_snapshot', 'aseguradora_nombre', 'tipo_sangre'].forEach(id => {
        const el = document.getElementById(id);
        if (!el) return;
        el.readOnly = true;
        el.tabIndex = -1;
        el.style.background = '#eef0f2';
        el.style.borderColor = '#cbd5e1';
        el.style.color = '#495057';
        el.style.cursor = 'not-allowed';
    });
}

// Contraparte de bloquearCamposIdentificacionPaciente(): se usa al limpiar el formulario
// para permitir buscar/registrar un paciente distinto.
function desbloquearCamposIdentificacionPaciente() {
    ['fecha_elabora_paciente', 'num_identificacion', 'num_historia_clinica', 'nombres',
     'edad_snapshot', 'aseguradora_nombre', 'tipo_sangre'].forEach(id => {
        const el = document.getElementById(id);
        if (!el) return;
        el.readOnly = false;
        el.removeAttribute('tabindex');
        el.style.background = '';
        el.style.borderColor = '';
        el.style.color = '';
        el.style.cursor = '';
    });
}

// Función para obtener los datos completos del paciente en caché
function obtenerPacienteCache(numIdentificacion = null) {
    try {
        const cacheKey = 'paciente_completo_data_cache';
        const cacheData = localStorage.getItem(cacheKey);
        
        if (cacheData) {
            const parsedCache = JSON.parse(cacheData);
            
            // Si se especifica un num_identificacion, verificar que coincida
            if (numIdentificacion && parsedCache.num_identificacion !== numIdentificacion) {
                console.log(`Caché encontrada pero para otro paciente (${parsedCache.num_identificacion} vs ${numIdentificacion})`);
                return null;
            }
            
            // Verificar que la caché no sea muy antigua (opcional: más de 1 hora)
            const ahora = new Date().getTime();
            const unaHora = 60 * 60 * 1000; // 1 hora en milisegundos
            if (parsedCache.timestamp && (ahora - parsedCache.timestamp) > unaHora) {
                console.log('Caché expirada (más de 1 hora), limpiando...');
                localStorage.removeItem(cacheKey);
                return null;
            }
            
            return parsedCache;
        }
        return null;
    } catch (error) {
        console.error('Error al obtener caché del paciente:', error);
        return null;
    }
}

// Función para limpiar la caché del paciente
function limpiarPacienteCache() {
    localStorage.removeItem('paciente_completo_data_cache');
    // Mantener compatibilidad con caché antigua
    localStorage.removeItem('paciente_actual_cache');
    localStorage.removeItem('paciente_completo_cache');
    console.log('✅ Caché del paciente limpiada completamente');
}

// Función para buscar formularios existentes del paciente (mantenida para compatibilidad)
async function buscarFormularioExistente(pacienteId, numIdentificacion) {
    try {
        // Buscar formularios por paciente o por num_identificacion
        let formularios = null;
        if (pacienteId) {
            formularios = await apiRequest(`/formularios/?paciente=${pacienteId}`);
        } else if (numIdentificacion) {
            formularios = await apiRequest(`/formularios/?paciente__num_identificacion=${numIdentificacion}`);
        }
        
        if (!formularios) return null;
        
        // DRF devuelve resultados paginados con formato {results: [...]}
        const listaFormularios = formularios?.results || formularios || [];
        
        if (listaFormularios.length > 0) {
            // Retornar el formulario más reciente
            return listaFormularios[0];
        }
        return null;
    } catch (error) {
        console.error('Error al buscar formulario existente:', error);
        return null;
    }
}

// Función para bloquear/desbloquear una columna completa
function bloquearColumna(horaIndex, bloquear = true) {
    // Bloquear todos los inputs de datos de esa columna
    const dataInputs = document.querySelectorAll(`.data-input[data-hora-index="${horaIndex}"]`);
    dataInputs.forEach(input => {
        if (bloquear) {
            input.disabled = true;
            input.readOnly = true;
            input.style.backgroundColor = '#f0f0f0';
            input.style.cursor = 'not-allowed';
            input.setAttribute('data-bloqueado', 'true');
        } else {
            input.disabled = false;
            input.readOnly = false;
            input.style.backgroundColor = '';
            input.style.cursor = '';
            input.removeAttribute('data-bloqueado');
        }
    });
    
    // Bloquear el input de tiempo de esa columna
    const timeInput = document.querySelector(`.time-input[data-hora-index="${horaIndex}"]`);
    if (timeInput) {
        if (bloquear) {
            timeInput.disabled = true;
            timeInput.readOnly = true;
            timeInput.style.backgroundColor = '#f0f0f0';
            timeInput.style.cursor = 'not-allowed';
            timeInput.setAttribute('data-bloqueado', 'true');
        } else {
            timeInput.disabled = false;
            timeInput.readOnly = false;
            timeInput.style.backgroundColor = '';
            timeInput.style.cursor = '';
            timeInput.removeAttribute('data-bloqueado');
        }
    }
}

// Función para desbloquear todas las columnas
function desbloquearTodasLasColumnas() {
    const timeInputs = document.querySelectorAll('.time-input');
    timeInputs.forEach((input, index) => {
        bloquearColumna(index, false);
    });
}

// Función para limpiar la tabla de mediciones informativa (acordeón superior)
function limpiarFormularioInformativo() {
    // 0. Limpiar/ocultar nueva vista previa clínica si existe
    const previewContainer = document.getElementById('vista-previa-paciente');
    if (previewContainer) previewContainer.style.display = 'none';
    const btnPreview = document.getElementById('btn-vista-previa');
    if (btnPreview) btnPreview.textContent = 'Vista Previa';
    const previewScroll = document.getElementById('preview-mediciones-scroll');
    if (previewScroll) {
        previewScroll.innerHTML = '';
    }
    const totalControles = document.getElementById('preview-total-controles');
    if (totalControles) totalControles.textContent = '0 REGISTROS';

    const collapsibleBody = document.querySelector('.collapsible-body');
    if (!collapsibleBody) return;

    // 1. Limpiar fechas/horas del encabezado
    collapsibleBody.querySelectorAll('.info-time').forEach(span => {
        span.textContent = '';
    });

    // 2. Limpiar todos los valores de datos
    collapsibleBody.querySelectorAll('.data-cell .info-value').forEach(span => {
        span.textContent = '-';
    });

    // 3. Limpiar datos del paciente en el encabezado
    collapsibleBody.querySelectorAll('.patient-table .info-value, .form-footer .info-value').forEach(span => {
        span.textContent = '-';
    });

    // 4. Vaciar el cuerpo de la tabla de mediciones para forzar regeneración
    const medicionesBody = collapsibleBody.querySelector('#mediciones-informativa-body');
    if (medicionesBody) {
        medicionesBody.innerHTML = '';
    }
}

// Limpiar todos los campos del formulario y el grid
function limpiarFormulario() {
    console.log('🧹 Limpiando campos del formulario y reiniciando grid...');
    
    // Limpiar vista informativa superior
    limpiarFormularioInformativo();
    
    // Limpiar caché del paciente al limpiar el formulario
    limpiarPacienteCache();
    
    // IDs de campos a limpiar
    const camposALimpiar = [
        'paciente_id', 'formulario_id', 'num_historia_clinica', 
        'nombres', 'tipo_sangre', 'fecha_elabora_paciente', 
        'diagnostico', 'edad_snapshot', 'edad_gestion', 
        'n_controles_prenatales', 'responsable', 'aseguradora_nombre'
    ];

    camposALimpiar.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.value = '';
    });
    
    // Restablecer fecha actual en fecha_elabora_paciente
    const fechaElaboraPaciente = document.getElementById('fecha_elabora_paciente');
    if (fechaElaboraPaciente) {
        fechaElaboraPaciente.value = obtenerFechaLocalColombia();
    }

    // Desbloquear todas las columnas antes de limpiar
    desbloquearTodasLasColumnas();

    // Volver a habilitar los campos de identificación para poder buscar otro paciente
    desbloquearCamposIdentificacionPaciente();

    // Limpiar variables de mediciones para la nueva interfaz
    if (window.medicionesPendientes) {
        window.medicionesPendientes = [];
    }
    
    // Limpiar el estado visual de los botones de parámetros
    document.querySelectorAll('.btn-parametro').forEach(btn => {
        const id = btn.getAttribute('data-parametro-id');
        if (id) actualizarBotonUI(id);
    });

    const timeGlobal = document.getElementById('hora_registro_actual');
    if (timeGlobal) timeGlobal.value = '';

    // Limpiar el grid original (por si queda algo en la interfaz colapsable o DOM viejo)
    document.querySelectorAll('.data-input, .data-input-modal').forEach(input => {
        input.value = '';
        input.disabled = false;
        input.readOnly = false;
        input.style.backgroundColor = '';
        input.style.cursor = '';
    });
    
    // Limpiar los inputs de tiempo
    document.querySelectorAll('.time-input').forEach(input => {
        input.value = '';
        input.disabled = false;
        input.readOnly = false;
        input.style.backgroundColor = '';
        input.style.cursor = '';
    });

    // REINICIAR COLUMNAS PROGRESIVAS: Ocultar todas excepto la Hora 0
    const tables = document.querySelectorAll('table.control-grid[data-progressive-hours]');
    tables.forEach(table => {
        table.setAttribute('data-progressive-last-visible', '0');
        // Ocultar todas las celdas de horas 1-9
        for (let h = 1; h <= 9; h++) {
            table.querySelectorAll('.col-hour-' + h).forEach(el => {
                el.classList.add('progressive-hours-hidden');
            });
        }
    });
    
    // Limpiar biometría
    const imgH = document.getElementById('imgHuella');
    const imgF = document.getElementById('imgFirma');
    if (imgH) { imgH.src = ''; imgH.style.display = 'none'; }
    if (imgF) { imgF.src = ''; imgF.style.display = 'none'; }
    const estH = document.getElementById('estadoHuella');
    const estF = document.getElementById('estadoFirma');
    if (estH) { estH.innerHTML = 'No capturada'; estH.style.display = 'block'; }
    if (estF) { estF.innerHTML = 'Firma pendiente'; estF.style.display = 'block'; }
    const btnVerH = document.getElementById('btnVerHuella');
    if (btnVerH) btnVerH.style.display = 'none';

    // Restablecer el botón a "Guardar"
    actualizarTextoBoton(false);
}

// Función para obtener la fecha local de Colombia (UTC-5) en formato YYYY-MM-DD
// Esta función usa la zona horaria local del navegador en lugar de UTC
function obtenerFechaLocalColombia() {
    const ahora = new Date();
    // Obtener la fecha local considerando la zona horaria del navegador
    // Esto evita problemas cuando el servidor está en UTC y el cliente en otra zona horaria
    const año = ahora.getFullYear();
    const mes = String(ahora.getMonth() + 1).padStart(2, '0');
    const dia = String(ahora.getDate()).padStart(2, '0');
    return `${año}-${mes}-${dia}`;
}

// Columnas progresivas: solo Hora 0 visible; al llenar una celda de la última columna visible, aparece la siguiente
function initProgressiveHours() {
    var tables = document.querySelectorAll('table.control-grid[data-progressive-hours]');
    tables.forEach(function (table) {
        if (table.classList.contains('progressive-hours')) return;
        table.classList.add('progressive-hours');

        var timeRow = table.querySelector('thead tr.time-row');
        var timeCells = timeRow ? timeRow.querySelectorAll('th.time-cell') : [];
        var numHours = timeCells.length;
        if (numHours < 2) return;

        timeCells.forEach(function (th, i) {
            var inp = th.querySelector('input.time-input');
            var idx = inp ? parseInt(inp.getAttribute('data-hora-index'), 10) : i;
            if (isNaN(idx)) idx = i;
            th.classList.add('col-hour-' + idx);
            if (idx >= 1) th.classList.add('progressive-hours-hidden');
        });

        table.querySelectorAll('tbody tr').forEach(function (tr) {
            if (tr.classList.contains('section-header')) return;
            var cells = tr.querySelectorAll('td.data-cell');
            cells.forEach(function (td, i) {
                var first = td.querySelector('.data-input');
                var idx = first ? parseInt(first.getAttribute('data-hora-index'), 10) : i;
                if (isNaN(idx)) idx = i;
                td.classList.add('col-hour-' + idx);
                if (idx >= 1) td.classList.add('progressive-hours-hidden');
            });
        });

        table.setAttribute('data-progressive-last-visible', '0');

        table.addEventListener('change', function (e) {
            var input = e.target;
            if (!input.classList.contains('data-input')) return;
            var table = input.closest('table.control-grid[data-progressive-hours]');
            if (!table) return;
            var last = parseInt(table.getAttribute('data-progressive-last-visible'), 10);
            if (isNaN(last)) last = 0;
            var hi = parseInt(input.getAttribute('data-hora-index'), 10);
            if (isNaN(hi)) return;
            var val = (input.value || '').trim();
            if (hi !== last || !val) return;
            var next = last + 1;
            if (next >= numHours) return;

            var nextCells = table.querySelectorAll('.col-hour-' + next);
            nextCells.forEach(function (el) { el.classList.remove('progressive-hours-hidden'); });
            table.setAttribute('data-progressive-last-visible', String(next));
        });
    });
}

function revealProgressiveHoursUpTo(maxHour) {
    if (maxHour == null || maxHour < 0) return;
    var tables = document.querySelectorAll('table.control-grid[data-progressive-hours]');
    tables.forEach(function (table) {
        var last = parseInt(table.getAttribute('data-progressive-last-visible'), 10);
        if (isNaN(last)) last = 0;
        var to = Math.max(last, maxHour);
        for (var h = 1; h <= to; h++) {
            table.querySelectorAll('.col-hour-' + h).forEach(function (el) {
                el.classList.remove('progressive-hours-hidden');
            });
        }
        table.setAttribute('data-progressive-last-visible', String(to));
    });
}

// Inicialización
document.addEventListener('DOMContentLoaded', function() {
    console.log('DOM cargado, inicializando aplicación...');
    
    // Cargar aseguradoras al iniciar
    cargarAseguradoras();

    // Cargar mapa de campos por parámetro (para resolver campo_id en modales sin data-campo-id)
    loadParamCamposMap();

    initProgressiveHours();
    
    // Asegurar que los campos de fecha del grid estén vacíos (sin valores por defecto)
    document.querySelectorAll('.time-input').forEach(input => {
        input.value = '';
    });
    
    // Establecer fecha actual por defecto
    const hoy = obtenerFechaLocalColombia();
    const fechaElabora = document.getElementById('fecha_elabora');
    if (fechaElabora && !fechaElabora.value) {
        fechaElabora.value = hoy;
    }
    
    // Establecer fecha actual por defecto en fecha_elabora_paciente
    const fechaElaboraPaciente = document.getElementById('fecha_elabora_paciente');
    if (fechaElaboraPaciente) {
        fechaElaboraPaciente.value = hoy;
    }

    // Recalcular edad cuando cambie la fecha de nacimiento (fecha_elabora_paciente)
    const fechaNacimientoInput = document.getElementById('fecha_elabora_paciente');
    const edadInput = document.getElementById('edad_snapshot');
    if (fechaNacimientoInput && edadInput) {
        fechaNacimientoInput.addEventListener('change', function() {
            if (this.value) {
                edadInput.value = calcularEdad(this.value);
                console.log(`🎂 Edad recalculada manualmente: ${edadInput.value}`);
            }
        });
    }
    
    // Búsqueda automática deshabilitada por petición del usuario para evitar interrupciones 
    // en el registro de pacientes nuevos. Los flujos se separan:
    // 1. Consulta: Exclusivamente por botones de búsqueda.
    // 2. Registro: Flujo manual sin interferencias.
    const numIdentificacionInput = document.getElementById('num_identificacion');
    if (numIdentificacionInput) {
        console.log('Búsqueda automática por blur deshabilitada para mejorar flujo de ingreso.');
    }

    // Listener para cambios en la hora del control actual (actualiza todos los botones)
    const horaRegistroInput = document.getElementById('hora_registro_actual');
    if (horaRegistroInput) {
        inicializarHoraRegistroAutomatica();
        horaRegistroInput.addEventListener('change', function() {
            console.log('Cambio de hora detectado, actualizando botones...');
            document.querySelectorAll('.btn-parametro-premium').forEach(btn => {
                const id = btn.getAttribute('data-parametro-id');
                if (id) actualizarBotonUI(id);
            });
        });
    }

    // Listener delegado para los inputs de los modales (Captura en tiempo real)
    document.addEventListener('input', function(e) {
        if (e.target.classList.contains('data-input-modal')) {
            registrarCambioDatoModal(e.target);
        }
    });

    // Detectar también cambios en selects de modales
    document.addEventListener('change', function(e) {
        if (e.target.classList.contains('data-input-modal') && e.target.tagName === 'SELECT') {
            registrarCambioDatoModal(e.target);
            mostrarAutoGuardado();
            // Excepción: el select de MEMBRANAS en "Rotas" deja el modal abierto
            // para que se alcance a diligenciar la hora de la ruptura debajo.
            const esMembranasRotas = e.target.id === 'select-membranas' && e.target.value === 'Rotas';
            if (!esMembranasRotas) {
                // Cerrar automáticamente el modal de medición tras seleccionar un valor.
                cerrarModalDesdeElemento(e.target);
            }
        }
    });

    // Para inputs/fechas/horas: guardar en blur y cerrar automáticamente.
    document.addEventListener('blur', function(e) {
        const target = e.target;
        if (!target || !target.classList || !target.classList.contains('data-input-modal')) return;
        if (target.tagName === 'SELECT') return;

        registrarCambioDatoModal(target);
        const valor = (target.value || '').trim();
        if (valor) {
            mostrarAutoGuardado();
            cerrarModalDesdeElemento(target);
        }
    }, true);

    // Permitir cerrar tocando/clickeando fuera del contenido del modal.
    document.addEventListener('click', function(e) {
        const overlay = e.target;
        if (!overlay || !overlay.classList || !overlay.classList.contains('modal-parametro')) return;
        const match = overlay.id ? overlay.id.match(/^modal-parametro-(\d+)$/) : null;
        if (match && match[1]) cerrarModalParametro(match[1]);
    });
    
    const formulario = document.getElementById('formulario-clinico');
    if (formulario) {
        console.log('Formulario encontrado, registrando event listener para submit...');
        
        formulario.addEventListener('submit', async function(e) {
            e.preventDefault();
            e.stopPropagation();
            console.log('Submit del formulario detectado, iniciando guardado...');
            
            // Deshabilitar el botón para evitar doble envío
            const btnGuardar = document.getElementById('btn-guardar');
            if (btnGuardar) {
                btnGuardar.disabled = true;
                btnGuardar.textContent = 'Guardando...';
            }
            
            try {
                await guardarFormulario();
                console.log('Formulario guardado exitosamente');
            } catch (error) {
                console.error('Error en guardarFormulario:', error);
                mostrarMensaje('Error al guardar formulario', 'error');
            } finally {
                // Rehabilitar el botón y restaurar texto según si es actualización
                if (btnGuardar) {
                    btnGuardar.disabled = false;
                    const formularioId = obtenerValorInput('formulario_id');
                    if (formularioId) {
                        btnGuardar.textContent = 'Actualizar Formulario';
                    } else {
                        btnGuardar.textContent = 'Guardar Formulario';
                    }
                }
            }
        });
        
        console.log('Event listener registrado correctamente');
    } else {
        console.error('ERROR: No se encontró el formulario con id "formulario-clinico"');
    }
    
    // Nota: el guardado se maneja únicamente desde el listener 'submit' de arriba.
    // Antes existía un segundo listener 'click' sobre #btn-guardar que llamaba
    // e.preventDefault() en el propio click del botón submit, lo cual cancelaba la
    // validación nativa (required) del navegador antes de que el evento 'submit'
    // llegara a dispararse. Se quitó para que 'required' vuelva a funcionar.


    
    // Función para cargar mediciones guardadas en el grid
    // Ahora acepta datos directamente (medicionesData) para evitar petición HTTP adicional
    async function cargarMedicionesEnGrid(formularioId, medicionesData = null) {
        try {
            let mediciones;
            
            if (medicionesData) {
                // Usar datos proporcionados directamente (desde endpoint consolidado)
                console.log(`Cargando mediciones desde datos proporcionados para el formulario ${formularioId}...`);
                mediciones = medicionesData;
            } else {
                // Hacer petición HTTP (compatibilidad retroativa)
            console.log(`Cargando mediciones para el formulario ${formularioId}...`);
                mediciones = await apiRequest(`/formularios/${formularioId}/mediciones/`);
            }
            
            console.log('Mediciones recibidas:', mediciones);

            if (!mediciones || mediciones.length === 0) {
                console.log('No hay mediciones guardadas para este formulario.');
                return;
            }

            // 1. Identificar todas las horas únicas y ordenarlas
            const horasUnicas = [...new Set(mediciones.map(m => m.tomada_en))].sort();
            console.log('Horas detectadas:', horasUnicas);

            // 2. Llenar los inputs de tiempo (encabezado del grid)
            const timeInputs = document.querySelectorAll('.time-input');
            const horaToIndexMap = {};
            const columnasConDatos = new Set(); // Para rastrear qué columnas tienen datos

            horasUnicas.forEach((hora, index) => {
                if (index < timeInputs.length) {
                    // Convertir a formato local para datetime-local input (YYYY-MM-DDTHH:MM)
                    const date = new Date(hora);
                    const localISO = new Date(date.getTime() - (date.getTimezoneOffset() * 60000))
                                        .toISOString().slice(0, 16);
                    
                    timeInputs[index].value = localISO;
                    horaToIndexMap[hora] = index;
                }
            });

            // 3. Limpiar grid antes de cargar (opcional, pero recomendado)
            document.querySelectorAll('.data-input').forEach(input => input.value = '');

            // 4. Llenar los valores en las celdas y rastrear columnas con datos
            mediciones.forEach(medicion => {
                const horaIndex = horaToIndexMap[medicion.tomada_en];
                if (horaIndex === undefined) return; // Superó las 12 columnas

                // Usamos el ID del parámetro desde el objeto anidado (parametro.id)
                const parametroId = medicion.parametro ? medicion.parametro.id : null;
                if (!parametroId) return;

                medicion.valores.forEach(v => {
                    // Usamos el ID del campo desde el objeto anidado (v.campo.id)
                    const campoId = v.campo ? v.campo.id : null;
                    if (!campoId) return;

                    const selector = `.data-input[data-parametro-id="${parametroId}"][data-campo-id="${campoId}"][data-hora-index="${horaIndex}"]`;
                    const input = document.querySelector(selector);
                    
                    if (input) {
                        // Obtener el valor no nulo y formatearlo
                        // Priorizar valor_text sobre valor_number (para compatibilidad con datos antiguos)
                        let valor = '';
                        let valorAsignado = false;
                        
                        if (v.valor_text !== null && v.valor_text !== undefined) {
                            valor = v.valor_text;
                        } else if (v.valor_number !== null && v.valor_number !== undefined) {
                            // Compatibilidad con datos antiguos que puedan estar en valor_number
                            valor = parseFloat(v.valor_number);
                            if (Number.isInteger(valor)) valor = parseInt(valor);
                            valor = valor.toString();
                        } else if (v.valor_boolean !== null) {
                            // Para campos booleanos, convertir a texto
                            valor = v.valor_boolean ? 'SÍ' : 'NO';
                        } else if (v.valor_json !== null) {
                            valor = JSON.stringify(v.valor_json);
                        }
                        
                        // Si es un select, buscar la opción que coincida
                        if (input.tagName === 'SELECT' && valor !== '') {
                            const opciones = Array.from(input.options);
                            
                            // Para campos booleanos, buscar opción que comience con "Sí" o "No"
                            if (v.valor_boolean !== null) {
                                const opcionEncontrada = opciones.find(opt => {
                                    const texto = opt.value.toUpperCase();
                                    if (v.valor_boolean) {
                                        return texto.startsWith('SÍ') || texto.startsWith('SI');
                                    } else {
                                        return texto.startsWith('NO');
                                    }
                                });
                                if (opcionEncontrada) {
                                    input.value = opcionEncontrada.value;
                                    valorAsignado = true;
                                }
                            }
                            
                            // Si aún no se asignó, buscar coincidencia exacta
                            if (!valorAsignado) {
                                let opcionEncontrada = opciones.find(opt => opt.value === valor);
                                // Si no hay coincidencia exacta, buscar por coincidencia parcial
                                if (!opcionEncontrada) {
                                    opcionEncontrada = opciones.find(opt => 
                                        opt.value.includes(valor) || valor.includes(opt.value)
                                    );
                                }
                                if (opcionEncontrada) {
                                    input.value = opcionEncontrada.value;
                                    valorAsignado = true;
                                }
                            }
                            
                            // Si no se encuentra ninguna opción, asignar el valor directamente
                            if (!valorAsignado) {
                                input.value = valor;
                            }
                        } else {
                            // Para inputs normales, asignar el valor directamente
                            input.value = valor;
                        }
                        
                        // Si el valor no está vacío, marcar esta columna como con datos
                        if (valor !== '' && valor !== null && valor !== undefined) {
                            columnasConDatos.add(horaIndex);
                        }
                    }
                });
            });

            // 5. Bloquear todas las columnas que tienen al menos un dato
            columnasConDatos.forEach(horaIndex => {
                bloquearColumna(horaIndex, true);
                console.log(`Columna ${horaIndex} bloqueada (tiene datos)`);
            });

            // 6. Revelar columnas progresivas hasta la última con datos
            var maxHora = columnasConDatos.size ? Math.max.apply(null, Array.from(columnasConDatos)) : -1;
            if (typeof revealProgressiveHoursUpTo === 'function') revealProgressiveHoursUpTo(maxHora);

            console.log('Grid poblado con éxito. Columnas con datos bloqueadas:', Array.from(columnasConDatos));
        } catch (error) {
            console.error('Error al cargar mediciones en el grid:', error);
            mostrarMensaje('Error al cargar mediciones guardadas', 'error');
        }
    }
    
    // Función para generar HTML del PDF desde datos de caché
    async function generarHTMLPDFDesdeCache() {
        try {
            // Obtener datos de la caché
            const numIdentificacion = obtenerValorInput('num_identificacion');
            if (!numIdentificacion) {
                mostrarMensaje('No hay paciente seleccionado para generar PDF', 'error');
                return null;
            }
            
            const cacheData = obtenerPacienteCache(numIdentificacion);
            if (!cacheData || !cacheData.paciente) {
                console.log('No hay datos en caché, obteniendo desde API...');
                // Si no hay caché, obtener datos
                const data = await buscarPacienteCompleto(numIdentificacion, false);
                // Verificar si el paciente fue encontrado (nuevo formato sin errores 404)
                if (!data || data.encontrado === false || !data.paciente) {
                    const mensaje = data?.mensaje || 'No se encontraron datos del paciente';
                    mostrarMensaje(mensaje, 'error');
                    return null;
                }
                return data;
            }
            
            console.log('✅ Usando datos de caché para generar PDF');
            return cacheData;
        } catch (error) {
            console.error('Error al obtener datos para PDF:', error);
            mostrarMensaje('Error al obtener datos para PDF: ' + error.message, 'error');
            return null;
        }
    }
    
    // Función para formatear hora a formato 12 horas
    function formatearHora12h(fechaISO) {
        try {
            const date = new Date(fechaISO);
            let horas = date.getHours();
            const minutos = date.getMinutes();
            const ampm = horas >= 12 ? 'p. m.' : 'a. m.';
            horas = horas % 12;
            horas = horas ? horas : 12;
            return `${horas.toString().padStart(2, '0')}:${minutos.toString().padStart(2, '0')} ${ampm}`;
        } catch (e) {
            return fechaISO;
        }
    }
    
    // Función para formatear fecha
    function formatearFecha(fecha) {
        if (!fecha) return '—';
        try {
            const date = new Date(fecha);
            return date.toLocaleDateString('es-ES', {
                day: '2-digit',
                month: '2-digit',
                year: 'numeric'
            });
        } catch (e) {
            return fecha;
        }
    }
    
    // Función para construir grid_data desde mediciones
    function construirGridData(mediciones) {
        const gridData = {};
        
        if (!mediciones || mediciones.length === 0) {
            return gridData;
        }
        
        mediciones.forEach(medicion => {
            const parametroId = medicion.parametro ? medicion.parametro.id : null;
            if (!parametroId) return;
            
            // Usar ISO format para la hora
            const horaISO = medicion.tomada_en;
            
            if (!gridData[parametroId]) {
                gridData[parametroId] = {};
            }
            if (!gridData[parametroId][horaISO]) {
                gridData[parametroId][horaISO] = {};
            }
            
            // Procesar valores
            if (medicion.valores && medicion.valores.length > 0) {
                medicion.valores.forEach(v => {
                    const campoId = v.campo ? v.campo.id : null;
                    if (!campoId) return;
                    
                    let valor = '—';
                    
                    if (v.valor_text !== null && v.valor_text !== undefined) {
                        valor = v.valor_text;
                        // Convertir tiempo a formato 12 horas si es necesario
                        const parametroIdNum = parseInt(parametroId);
                        const campoIdNum = parseInt(campoId);
                        if ((parametroIdNum === 17 && campoIdNum === 19) || (parametroIdNum === 14 && campoIdNum === 18)) {
                            const horaMatch = valor.match(/^(\d{1,2}):(\d{2})$/);
                            if (horaMatch) {
                                let horas = parseInt(horaMatch[1]);
                                const minutos = horaMatch[2];
                                const ampm = horas >= 12 ? 'p. m.' : 'a. m.';
                                horas = horas % 12;
                                horas = horas ? horas : 12;
                                valor = `${horas.toString().padStart(2, '0')}:${minutos} ${ampm}`;
                            }
                        }
                    } else if (v.valor_number !== null && v.valor_number !== undefined) {
                        valor = parseFloat(v.valor_number);
                        if (Number.isInteger(valor)) valor = parseInt(valor);
                        valor = valor.toString();
                    } else if (v.valor_boolean !== null && v.valor_boolean !== undefined) {
                        valor = v.valor_boolean ? 'SÍ' : 'NO';
                        // Casos especiales para booleanos
                        if (parametroIdNum === 11 && campoIdNum === 14) {
                            valor = v.valor_boolean ? 'Sí - Bolsa amniótica íntegra' : 'No - Ya hubo ruptura';
                        } else if (parametroIdNum === 12 && campoIdNum === 15) {
                            valor = v.valor_boolean ? 'Sí – Espontánea o artificial' : 'No - Membranas aún íntegras';
                        }
                    } else if (v.valor_json !== null && v.valor_json !== undefined) {
                        valor = JSON.stringify(v.valor_json);
                    }
                    
                    gridData[parametroId][horaISO][campoId] = valor;
                });
            }
        });
        
        return gridData;
    }
    
    // Función para cargar el template HTML del PDF
    async function cargarTemplatePDF() {
        try {
            // Este proyecto actualmente no expone un template HTML de impresión
            // en el frontend estático. Para evitar 404 repetidos en consola,
            // sólo intentamos cargarlo si se define explícitamente una ruta.
            const appConfig = (typeof window !== 'undefined')
                ? (window.APP_CONFIG || window.AppConfig || null)
                : null;
            const rutaTemplateConfig =
                (appConfig && appConfig.PDF_TEMPLATE_PATH)
                    ? String(appConfig.PDF_TEMPLATE_PATH).trim()
                    : '';
            
            if (!rutaTemplateConfig) {
                return null;
            }
            
            const rutasPosibles = [rutaTemplateConfig];
            
            for (const ruta of rutasPosibles) {
                try {
                    const response = await fetch(ruta);
                    if (response.ok) {
                        const htmlTemplate = await response.text();
                        console.log(`✅ Template HTML cargado correctamente desde: ${ruta}`);
                        return htmlTemplate;
                    }
                } catch (e) {
                    // Continuar con la siguiente ruta
                    continue;
                }
            }
            
            throw new Error(`No se pudo cargar el template PDF configurado: ${rutaTemplateConfig}`);
        } catch (error) {
            console.error('Error al cargar template HTML:', error);
            // Si falla, retornar null para usar el método anterior
            return null;
        }
    }
    
    // Función para reemplazar placeholders en el template
    function reemplazarPlaceholders(template, replacements) {
        let html = template;
        for (const [key, value] of Object.entries(replacements)) {
            const regex = new RegExp(`{{${key}}}`, 'g');
            html = html.replace(regex, value || '—');
        }
        return html;
    }
    
    // Función para generar el grid de mediciones dinámicamente
    // Ahora incluye items y parámetros vacíos (sin mediciones)
    function generarGridMediciones(items, horasUnicas, gridData, mediciones) {
        let gridHTML = '';
        
        items.forEach(item => {
            // Incluir el item incluso si no tiene parámetros (mostrará vacío)
            if (!item.parametros || item.parametros.length === 0) {
                // Si el item no tiene parámetros, mostrar solo la fila del item
                gridHTML += `
                    <tr class="section-row">
                        <td colspan="11">${item.nombre || 'ITEM'}</td>
                    </tr>`;
            return;
        }

            gridHTML += `
                    <tr class="section-row">
                        <td colspan="11">${item.nombre || 'ITEM'}</td>
                    </tr>`;
            
            item.parametros.forEach(param => {
                // Obtener campos del parámetro desde las mediciones
                const camposMap = new Map();
                mediciones.forEach(m => {
                    if (m.parametro && m.parametro.id === param.id) {
                        if (m.valores) {
                            m.valores.forEach(v => {
                                if (v.campo && !camposMap.has(v.campo.id)) {
                                    camposMap.set(v.campo.id, v.campo);
                                }
                            });
                        }
                    }
                });
                
                // Si no hay campos en mediciones, obtenerlos del parámetro directamente (desde BD)
                if (camposMap.size === 0 && param.campos && param.campos.length > 0) {
                    param.campos.forEach(campo => {
                        camposMap.set(campo.id, campo);
                    });
                }
                
                const campos = Array.from(camposMap.values());
                
                gridHTML += `
                        <tr>
                            <td class="param-name">${param.nombre || 'PARÁMETRO'}</td>`;
                
                // Si hay horas únicas, mostrar valores para cada hora
                if (horasUnicas.length > 0) {
                    horasUnicas.forEach(horaISO => {
                        const paramData = gridData[param.id] || {};
                        const horaData = paramData[horaISO] || {};
                        
                        if (campos.length === 0) {
                            // Si no hay campos, mostrar celda vacía
                            gridHTML += `<td class="valor-celda">—</td>`;
                        } else {
                            // Mostrar valores de los campos
                            const valores = campos.map(campo => {
                                const valor = horaData[campo.id] || '—';
                                return `<div class="${campos.length > 1 ? 'multi-campo' : ''}">${valor}</div>`;
                            }).join('');
                            gridHTML += `<td class="valor-celda">${valores}</td>`;
                        }
                    });
                    
                    // Celdas vacías para completar las 10 columnas
                    const celdasVacias = 10 - horasUnicas.length;
                    for (let i = 0; i < celdasVacias; i++) {
                        gridHTML += '<td></td>';
                    }
                } else {
                    // Si no hay horas, mostrar 10 celdas vacías
                    for (let i = 0; i < 10; i++) {
                        gridHTML += '<td class="valor-celda">—</td>';
                    }
                }
                
                gridHTML += `
                        </tr>`;
            });
        });
        
        return gridHTML;
    }
    
    // Función para obtener todos los items y parámetros desde la base de datos
    async function obtenerTodosItemsParametros() {
        try {
            console.log('Obteniendo todos los items y parámetros desde la API...');
            
            // Obtener todos los items
            const itemsResponse = await apiRequest('/items/');
            const items = itemsResponse?.results || itemsResponse || [];
            
            console.log(`✅ Obtenidos ${items.length} items desde la API`);
            
            // Para cada item, obtener sus parámetros
            const itemsCompletos = await Promise.all(
                items.map(async (item) => {
                    try {
                        // Obtener parámetros del item
                        const parametrosResponse = await apiRequest(`/items/${item.id}/parametros/`);
                        const parametros = parametrosResponse?.results || parametrosResponse || [];
                        
                        // Para cada parámetro, obtener sus campos
                        const parametrosCompletos = await Promise.all(
                            parametros.map(async (param) => {
                                try {
                                    const camposResponse = await apiRequest(`/parametros/${param.id}/campos/`);
                                    const campos = camposResponse?.results || camposResponse || [];
                                    return {
                                        ...param,
                                        campos: campos
                                    };
                                } catch (error) {
                                    console.warn(`Error al obtener campos del parámetro ${param.id}:`, error);
                                    return {
                                        ...param,
                                        campos: []
                                    };
                                }
                            })
                        );
                        
                        return {
                            ...item,
                            parametros: parametrosCompletos
                        };
                    } catch (error) {
                        console.warn(`Error al obtener parámetros del item ${item.id}:`, error);
                        return {
                            ...item,
                            parametros: []
                        };
                    }
                })
            );
            
            console.log('✅ Items y parámetros completos obtenidos:', itemsCompletos);
            return itemsCompletos;
        } catch (error) {
            console.error('Error al obtener items y parámetros desde la API:', error);
            return [];
        }
    }
    
    // Función para generar HTML completo del PDF usando el template
    async function generarHTMLPDF(data) {
        if (!data || !data.paciente || !data.formulario) {
            mostrarMensaje('No hay formulario para imprimir', 'error');
            return null;
        }
        
        const paciente = data.paciente;
        const formulario = data.formulario;
        const mediciones = data.mediciones || [];

        // Convierte rutas relativas (/media/...) a URLs absolutas del backend (http://host:puerto)
        function normalizarURLMedia(url, versionToken = '') {
            if (!url || typeof url !== 'string') return '';
            if (url.startsWith('data:')) return url;

            const agregarVersion = (urlBase) => {
                if (!versionToken) return urlBase;
                const sep = urlBase.includes('?') ? '&' : '?';
                return `${urlBase}${sep}v=${encodeURIComponent(versionToken)}`;
            };

            if (/^(https?:)?\/\//i.test(url)) return agregarVersion(url);
            try {
                const cfg = window.APP_CONFIG || window.AppConfig || {};
                const apiBase = cfg.API_BASE_URL || '';
                const backendOrigin = apiBase ? new URL(apiBase).origin : window.location.origin;
                return agregarVersion(`${backendOrigin}${url.startsWith('/') ? '' : '/'}${url}`);
            } catch (e) {
                return agregarVersion(url);
            }
        }
        
        // Fetch biometrics
        let huellaUrl = '';
        let firmaUrl = '';
        if (paciente && paciente.id) {
            try {
                // Usar apiRequest en lugar de fetch directo para asegurar la URL del backend correcta
                const huellaData = await apiRequest(`/huella/${paciente.id}/`);
                // Compatibilidad con ambas respuestas: legacy y actual del backend
                if (huellaData && (huellaData.encontrado || huellaData.status === 'ok')) {
                    const versionToken = huellaData.fecha || Date.now();
                    huellaUrl = normalizarURLMedia(huellaData.imagen_huella || huellaData.imagen_url || '', versionToken);
                    firmaUrl = normalizarURLMedia(huellaData.imagen_firma || huellaData.firma_url || '', versionToken);
                }
            } catch (error) {
                console.error('Error fetching biometrics for PDF:', error);
            }
        }
        
        // Agregar biometrias a la respuesta para el fallback
        data.huella = huellaUrl;
        data.firma = firmaUrl;

        // Cargar el template HTML
        let htmlTemplate = await cargarTemplatePDF();
        
        // Si no se puede cargar el template, usar el método anterior (fallback)
        if (!htmlTemplate) {
            console.log('⚠️ No se pudo cargar el template, usando generación dinámica...');
            return await generarHTMLPDFFallback(data);
        }
        
        // Obtener TODOS los items y parámetros desde la base de datos
        const todosItems = await obtenerTodosItemsParametros();
        
        // Construir estructura de items y parámetros desde las mediciones (para tener datos)
        const itemsMapDesdeMediciones = new Map();
        
        mediciones.forEach(medicion => {
            if (!medicion.parametro || !medicion.parametro.item) return;
            
            const item = medicion.parametro.item;
            const parametro = medicion.parametro;
            
            if (!itemsMapDesdeMediciones.has(item.id)) {
                itemsMapDesdeMediciones.set(item.id, {
                    item: item,
                    parametros: new Map()
                });
            }
            
            const itemData = itemsMapDesdeMediciones.get(item.id);
            if (!itemData.parametros.has(parametro.id)) {
                itemData.parametros.set(parametro.id, parametro);
            }
        });
        
        // Combinar items de la base de datos con los de las mediciones
        // Priorizar los datos de las mediciones (tienen más información), pero incluir todos los items
        const itemsMapCompleto = new Map();
        
        // Primero agregar todos los items de la base de datos
        todosItems.forEach(itemDB => {
            itemsMapCompleto.set(itemDB.id, {
                item: itemDB,
                parametros: new Map()
            });
            
            // Agregar todos los parámetros del item desde la base de datos
            if (itemDB.parametros && itemDB.parametros.length > 0) {
                itemDB.parametros.forEach(param => {
                    const itemData = itemsMapCompleto.get(itemDB.id);
                    itemData.parametros.set(param.id, param);
                });
            }
        });
        
        // Luego, actualizar con los datos de las mediciones (si existen)
        itemsMapDesdeMediciones.forEach((itemDataMedicion, itemId) => {
            if (itemsMapCompleto.has(itemId)) {
                const itemDataCompleto = itemsMapCompleto.get(itemId);
                
                // Actualizar parámetros con datos de mediciones (tienen más info como campos)
                itemDataMedicion.parametros.forEach((paramMedicion, paramId) => {
                    itemDataCompleto.parametros.set(paramId, paramMedicion);
                });
            }
        });
        
        // Convertir Map a Array ordenado
        const items = Array.from(itemsMapCompleto.values())
            .map(itemData => ({
                id: itemData.item.id,
                nombre: itemData.item.nombre,
                codigo: itemData.item.codigo,
                parametros: Array.from(itemData.parametros.values())
                    .sort((a, b) => (a.orden || a.id || 0) - (b.orden || b.id || 0))
            }))
            .sort((a, b) => (a.id || 0) - (b.id || 0));
        
        console.log('Items completos (con vacíos):', items);
        
        // Construir grid_data desde mediciones
        const gridData = construirGridData(mediciones);
        
        // Obtener horas únicas y ordenarlas
        const horasUnicas = [...new Set(mediciones.map(m => m.tomada_en))].sort().slice(0, 10);
        
        // Preparar replacements para el template
        const replacements = {
            'CODIGO': formulario.codigo || '—',
            'VERSION': formulario.version || '—',
            'NUM_HOJA': formulario.num_hoja || 1,
            'FECHA_ELABORA': formatearFecha(formulario.fecha_elabora),
            'PACIENTE_NOMBRES': paciente.nombres || '—',
            'PACIENTE_TIPO_SANGRE': paciente.tipo_sangre_display || paciente.tipo_sangre || '—',
            'PACIENTE_NUM_IDENTIFICACION': paciente.num_identificacion || '—',
            'PACIENTE_NUM_HISTORIA_CLINICA': paciente.num_historia_clinica || '—',
            'FORMULARIO_ASEGURADORA': formulario.aseguradora ? (formulario.aseguradora.nombre || 'N/A') : 'N/A',
            'FORMULARIO_EDAD_SNAPSHOT': formulario.edad_snapshot ? `${formulario.edad_snapshot} años` : '—',
            'FORMULARIO_EDAD_GESTION': formulario.edad_gestion ? `${formulario.edad_gestion} semanas` : '—',
            'FORMULARIO_ESTADO': formulario.estado_display || formulario.estado || '—',
            'FORMULARIO_N_CONTROLES_PRENATALES': formulario.n_controles_prenatales || '—',
            'FORMULARIO_DIAGNOSTICO': formulario.diagnostico || '—',
            'FORMULARIO_RESPONSABLE': formulario.responsable || '—',
            'LOGO_HOSPITAL': '/static/img/logo_hospital.png',
            'LOGO_ACREDITACION': '/static/img/logo_acreditacion.png',
            'HUELLA_IMG': huellaUrl || '',
            'HUELLA_DISPLAY': huellaUrl ? 'inline-block' : 'none',
            'NO_HUELLA_DISPLAY': huellaUrl ? 'none' : 'block',
            'FIRMA_IMG': firmaUrl || '',
            'FIRMA_DISPLAY': firmaUrl ? 'inline-block' : 'none',
            'NO_FIRMA_DISPLAY': firmaUrl ? 'none' : 'block'
        };
        
        // Reemplazar placeholders básicos
        let html = reemplazarPlaceholders(htmlTemplate, replacements);
        
        // Generar y reemplazar el header de horas
        const horasHeaderHTML = horasUnicas.map(h => 
            `<th class="time-col">${formatearHora12h(h)}</th>`
        ).join('') + Array(10 - horasUnicas.length).fill(0).map(() => '<th class="time-col"></th>').join('');
        html = html.replace('<tr id="horas-header">', `<tr id="horas-header">${horasHeaderHTML}`);
        html = html.replace('<!-- Las horas se insertan dinámicamente aquí -->', '');
        
        // Generar y reemplazar el grid de mediciones
        const gridHTML = generarGridMediciones(items, horasUnicas, gridData, mediciones);
        html = html.replace('<tbody id="grid-body">', `<tbody id="grid-body">${gridHTML}`);
        html = html.replace('<!-- El grid se inserta dinámicamente aquí -->', '');
        
        return html;
    }
    
    // Función fallback: generar HTML dinámicamente (método anterior)
    async function generarHTMLPDFFallback(data) {
        if (!data || !data.paciente || !data.formulario) {
            return null;
        }
        
        const paciente = data.paciente;
        const formulario = data.formulario;
        const mediciones = data.mediciones || [];
        
        // Construir estructura de items y parámetros desde las mediciones
        const itemsMap = new Map();
        
        mediciones.forEach(medicion => {
            if (!medicion.parametro || !medicion.parametro.item) return;
            
            const item = medicion.parametro.item;
            const parametro = medicion.parametro;
            
            if (!itemsMap.has(item.id)) {
                itemsMap.set(item.id, {
                    item: item,
                    parametros: new Map()
                });
            }
            
            const itemData = itemsMap.get(item.id);
            if (!itemData.parametros.has(parametro.id)) {
                itemData.parametros.set(parametro.id, parametro);
            }
        });
        
        const items = Array.from(itemsMap.values())
            .map(itemData => ({
                id: itemData.item.id,
                nombre: itemData.item.nombre,
                codigo: itemData.item.codigo,
                parametros: Array.from(itemData.parametros.values())
            }))
            .sort((a, b) => (a.id || 0) - (b.id || 0));
        
        const gridData = construirGridData(mediciones);
        const horasUnicas = [...new Set(mediciones.map(m => m.tomada_en))].sort().slice(0, 10);
        
        // Construir HTML (método anterior)
        const html = `
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <title>IMPRESIÓN - ${formulario.codigo || 'FORMULARIO'}</title>
    <style>
        @page {
            size: A4 portrait;
            margin: 1cm;
        }
        body {
            font-family: 'Segoe UI', Arial, sans-serif;
            font-size: 9pt;
            color: #333;
            margin: 0;
            padding: 0;
        }
        .container {
            width: 100%;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            margin-bottom: 8px;
        }
        th, td {
            border: 1px solid #000;
            padding: 4px 6px;
        }
        .header-table td {
            padding: 10px;
        }
        .info-label {
            font-weight: bold;
            background-color: #f3f4f6;
            width: 15%;
            padding: 1px 4px !important;
            vertical-align: middle;
            font-size: 8pt;
            line-height: 1.2;
        }
        .info-value {
            width: 35%;
            padding: 1px 4px !important;
            vertical-align: middle;
            font-size: 8pt;
            line-height: 1.2;
        }
        .logo-cell {
            width: 150px;
            text-align: center;
        }
        .title-cell {
            text-align: center;
        }
        .title-cell h1 {
            margin: 0;
            font-size: 14pt;
            color: #444;
        }
        .meta-cell {
            width: 180px;
            font-size: 8pt;
        }
        .grid-table {
            table-layout: fixed;
        }
        .grid-table th {
            background-color: #3b82f6;
            color: white;
            font-size: 7pt;
            text-align: center;
        }
        .grid-table .time-col {
            width: 8.4%;
            font-size: 6pt;
        }
        .grid-table .item-col {
            width: 16%;
        }
        .section-row {
            background-color: #e5e7eb;
            font-weight: bold;
            text-transform: uppercase;
            font-size: 7pt;
        }
        .param-name {
            font-weight: 500;
            font-size: 7pt;
        }
        .valor-celda {
            text-align: center;
            font-size: 7pt;
            height: 25px;
            vertical-align: middle;
        }
        .multi-campo {
            font-size: 6pt;
            border-bottom: 1px solid #eee;
        }
        .multi-campo:last-child {
            border-bottom: none;
        }
        @media print {
            .no-print {
                display: none;
            }
            body {
                -webkit-print-color-adjust: exact;
            }
        }
    </style>
</head>
<body onload="window.print(); setTimeout(() => window.close(), 500);">
    <div class="container">
        <!-- Encabezado Institucional -->
        <table class="header-table">
            <tr>
                <td class="logo-cell">
                    <!-- Logo placeholder -->
                </td>
                <td class="title-cell">
                    <h1>CONTROL DE TRABAJO DE PARTO</h1>
                </td>
                <td class="meta-cell">
                    <b>CÓDIGO:</b> ${formulario.codigo || '—'}<br>
                    <b>VERSIÓN:</b> ${formulario.version || '—'}<br>
                    <b>HOJA:</b> ${formulario.num_hoja || 1} DE 1<br>
                    <b>FECHA:</b> ${formatearFecha(formulario.fecha_elabora)}
                </td>
                <td class="accreditation-cell">
                    <!-- Logo acreditación placeholder -->
                </td>
            </tr>
        </table>

        <!-- Datos del Paciente -->
        <table>
            <tr>
                <td class="info-label">PACIENTE:</td>
                <td class="info-value">${paciente.nombres || '—'}</td>
                <td class="info-label">GRUPO SANGUÍNEO:</td>
                <td class="info-value">${paciente.tipo_sangre_display || paciente.tipo_sangre || '—'}</td>
            </tr>
            <tr>
                <td class="info-label">IDENTIFICACIÓN:</td>
                <td class="info-value">${paciente.num_identificacion || '—'}</td>
                <td class="info-label">H. CLÍNICA:</td>
                <td class="info-value">${paciente.num_historia_clinica || '—'}</td>
            </tr>
            <tr>
                <td class="info-label">ASEGURADORA:</td>
                <td class="info-value">${formulario.aseguradora ? (formulario.aseguradora.nombre || 'N/A') : 'N/A'}</td>
                <td class="info-label">EDAD:</td>
                <td class="info-value">${formulario.edad_snapshot || '—'} años</td>
            </tr>
            <tr>
                <td class="info-label">EDAD GESTACIONAL:</td>
                <td class="info-value">${formulario.edad_gestion || '—'} semanas</td>
                <td class="info-label">G_P_C_A_V_M:</td>
                <td class="info-value">${formulario.estado_display || formulario.estado || '—'}</td>
            </tr>
            <tr>
                <td class="info-label">N° CONTROLES PRENATALES:</td>
                <td class="info-value">${formulario.n_controles_prenatales || '—'}</td>
                <td class="info-label">DIAGNÓSTICO:</td>
                <td class="info-value">${formulario.diagnostico || '—'}</td>
            </tr>
        </table>

        <!-- Grid Principal -->
        <table class="grid-table">
            <thead>
                <tr>
                    <th class="item-col" rowspan="2">ÍTEM / PARÁMETRO</th>
                    <th colspan="10">HORA DE CONTROL</th>
                </tr>
                <tr>
                    ${horasUnicas.map(h => `<th class="time-col">${formatearHora12h(h)}</th>`).join('')}
                    ${Array(10 - horasUnicas.length).fill(0).map(() => '<th class="time-col"></th>').join('')}
                </tr>
            </thead>
            <tbody>
                ${items.map(item => {
                    if (!item.parametros || item.parametros.length === 0) return '';
                    
                    return `
                    <tr class="section-row">
                        <td colspan="11">${item.nombre || 'ITEM'}</td>
                    </tr>
                    ${item.parametros.map(param => {
                        // Obtener campos del parámetro desde las mediciones
                        const camposMap = new Map();
                        mediciones.forEach(m => {
                            if (m.parametro && m.parametro.id === param.id) {
                                if (m.valores) {
                                    m.valores.forEach(v => {
                                        if (v.campo && !camposMap.has(v.campo.id)) {
                                            camposMap.set(v.campo.id, v.campo);
                                        }
                                    });
                                }
                            }
                        });
                        
                        // Si no hay campos en mediciones, intentar obtenerlos del parámetro directamente
                        if (camposMap.size === 0 && param.campos) {
                            param.campos.forEach(campo => {
                                camposMap.set(campo.id, campo);
                            });
                        }
                        
                        const campos = Array.from(camposMap.values());
                        
                        return `
                        <tr>
                            <td class="param-name">${param.nombre || 'PARÁMETRO'}</td>
                            ${horasUnicas.map(horaISO => {
                                const paramData = gridData[param.id] || {};
                                const horaData = paramData[horaISO] || {};
                                
                                if (campos.length === 0) {
                                    return `<td class="valor-celda">—</td>`;
                                }
                                
                                const valores = campos.map(campo => {
                                    const valor = horaData[campo.id] || '—';
                                    return `<div class="${campos.length > 1 ? 'multi-campo' : ''}">${valor}</div>`;
                                }).join('');
                                
                                return `<td class="valor-celda">${valores}</td>`;
                            }).join('')}
                            ${Array(10 - horasUnicas.length).fill(0).map(() => '<td></td>').join('')}
                        </tr>
                        `;
                    }).join('')}
                    `;
                }).filter(html => html !== '').join('')}
            </tbody>
        </table>

        <!-- Responsable -->
        <table style="margin-top: 20px; border: none;">
            <tr>
                <td style="border: none;">
                    <b>RESPONSABLE:</b> ${formulario.responsable || '—'}
                </td>
            </tr>
        </table>
        
        <!-- Biometría -->
        <table style="margin-top: 30px; border: none; width: 100%;">
            <tr>
                <td style="border: none; width: 50%; text-align: center; vertical-align: bottom; height: 150px;">
                    <div style="min-height: 100px; margin-bottom: 10px;">
                        <img src="\${data.huella || ''}" alt="Huella" style="max-height: 100px; max-width: 150px; display: \${data.huella ? 'inline-block' : 'none'};">
                        <div style="display: \${data.huella ? 'none' : 'block'}; color: #999; font-style: italic; margin-top: 40px;">Sin huella registrada</div>
                    </div>
                    <div style="border-top: 1px solid #000; display: inline-block; width: 80%; padding-top: 5px;">
                        <b>HUELLA DACTILAR</b>
                    </div>
                    <div style="margin-top: 3px; font-size: 8pt;">\${paciente.nombres || '—'}</div>
                </td>
                <td style="border: none; width: 50%; text-align: center; vertical-align: bottom; height: 150px;">
                    <div style="min-height: 100px; margin-bottom: 10px;">
                        <img src="\${data.firma || ''}" alt="Firma" style="max-height: 100px; max-width: 250px; display: \${data.firma ? 'inline-block' : 'none'};">
                        <div style="display: \${data.firma ? 'none' : 'block'}; color: #999; font-style: italic; margin-top: 40px;">Sin firma registrada</div>
                    </div>
                    <div style="border-top: 1px solid #000; display: inline-block; width: 80%; padding-top: 5px;">
                        <b>FIRMA DEL PACIENTE</b>
                    </div>
                    <div style="margin-top: 3px; font-size: 8pt;">\${paciente.nombres || '—'}</div>
                </td>
            </tr>
            <tr>
                <td colspan="2" style="border: none; text-align: center; padding-top: 10px; font-size: 8pt; color: #666;">
                    Documento firmado biométricamente
                </td>
            </tr>
        </table>
    </div>
</body>
</html>
        `;
        
        return html;
    }

    /**
     * Descarga el PDF profesional generado por el backend.
     * @param {number} formularioId - ID opcional, si no se provee se busca en el DOM.
     */
    async function descargarPDF(formularioId = null) {
        console.log('🚀 Iniciando descarga de PDF (vía backend)...');
        
        // 1. Obtener ID del formulario
        if (!formularioId) {
            const el = document.getElementById('formulario_id');
            formularioId = el ? el.value : null;
        }
        
        if (!formularioId) {
            mostrarMensaje('Debe guardar el formulario antes de generar el PDF', 'warning');
            return;
        }

        try {
            // 2. Construir URL (prefijo /parto/ según urls.py global)
            const url = `/parto/formulario/${formularioId}/pdf/`;
            console.log(`📂 Abriendo reporte: ${url}`);
            
            // 3. Abrir en pestaña nueva (el navegador manejará la descarga/visualización)
            const win = window.open(url, '_blank');
            if (!win) {
                mostrarMensaje('Por favor habilite las ventanas emergentes', 'error');
            }
        } catch (error) {
            console.error('❌ Error al abrir PDF:', error);
            mostrarMensaje('Error al abrir el reporte profesional', 'error');
        }
    }

    // Exponer al ámbito global
    window.descargarPDF = descargarPDF;
});

// --- LÓGICA DE BIOMETRÍA Y FIRMA (GLOBAL) ---
let pollingHuellaInterval = null;
let signaturePad = null;

// Inicialización de Biometría al cargar el documento
document.addEventListener('DOMContentLoaded', () => {
    const canvas = document.getElementById('signature-pad');
    if (canvas) {
        signaturePad = new SignaturePad(canvas, {
            backgroundColor: 'rgb(255, 255, 255)'
        });
        
        // Ajustar tamaño del canvas al abrir el modal o cambiar tamaño
        window.addEventListener('resize', resizeCanvas);
    }
});

function resizeCanvas() {
    const canvas = document.getElementById('signature-pad');
    if (!canvas) return;
    const ratio = Math.max(window.devicePixelRatio || 1, 1);
    canvas.width = canvas.offsetWidth * ratio;
    canvas.height = canvas.offsetHeight * ratio;
    canvas.getContext("2d").scale(ratio, ratio);
    if (signaturePad) signaturePad.clear(); // Limpiar al redimensionar para evitar artifacts
}

async function abrirModalFirma() {
    // Si el paciente aún no se ha guardado (registro nuevo), guardarlo primero
    // para poder asociar la firma. Mismo resguardo que antes tenía "Firmar en tablet".
    let pacienteId = obtenerValorInput('paciente_id');
    if (!pacienteId) {
        try {
            const paciente = await guardarPaciente();
            if (!paciente || !paciente.id) return; // guardarPaciente ya muestra el error
        } catch (error) {
            console.error("❌ Error al guardar paciente previo a la firma:", error);
            mostrarMensaje(error.message || "Guarde los datos del paciente primero.", "warning");
            return;
        }
    }

    const modal = document.getElementById('modalFirma');
    if (modal) {
        modal.style.display = 'flex';
        // Ajustar tamaño del canvas después de mostrar el modal (importante para offsetWidth)
        setTimeout(resizeCanvas, 100);
    }
}

function cerrarModalFirma() {
    const modal = document.getElementById('modalFirma');
    if (modal) modal.style.display = 'none';
}

function limpiarFirma() {
    if (signaturePad) signaturePad.clear();
}

async function guardarFirmaDigital() {
    const pacienteId = obtenerValorInput('paciente_id');
    const formularioId = obtenerValorInput('formulario_id');
    
    if (!pacienteId) {
        mostrarMensaje("Seleccione un paciente primero", "error");
        return;
    }

    if (!signaturePad || signaturePad.isEmpty()) {
        mostrarMensaje("Por favor, realice la firma antes de guardar", "error");
        return;
    }

    const firmaB64 = signaturePad.toDataURL(); // Obtiene PNG base64

    try {
        mostrarMensaje("Guardando firma...", "info");
        const baseUrl = API_BASE_URL;
        
        const data = {
            paciente_id: pacienteId,
            formulario_id: formularioId || null,
            firma: firmaB64,
            usuario: obtenerValorInput('responsable') || "Sistema"
        };

        const response = await fetch(`${baseUrl}/guardar-huella/`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });

        if (response.ok) {
            mostrarMensaje("✅ Firma guardada con éxito", "success");
            cerrarModalFirma();
            // Disparar una actualización inmediata de la UI
            const resData = await response.json();
            // Forzamos un fetch de la última captura para actualizar la tarjeta
            const updateRes = await fetch(`${baseUrl}/huella/${pacienteId}/?_=${new Date().getTime()}`);
            if (updateRes.ok) {
                const updatedInfo = await updateRes.json();
                actualizarUIHuella(updatedInfo);
            }
        } else {
            throw new Error("Error al guardar en el servidor");
        }
    } catch (error) {
        console.error("Error al guardar firma:", error);
        mostrarMensaje("Error al guardar la firma: " + error.message, "error");
    }
}

function iniciarPollingHuella(pacienteId) {
    if (!pacienteId) return;
    
    console.log(`🔍 Iniciando polling de huella para paciente: ${pacienteId}`);
    
    if (pollingHuellaInterval) clearInterval(pollingHuellaInterval);
    
    const consultarHuellaUnaVez = async () => {
        try {
            const baseUrl = API_BASE_URL;
            const response = await fetch(`${baseUrl}/huella/${pacienteId}/?_=${new Date().getTime()}`);
            if (response.ok) {
                const data = await response.json();
                if (data && (data.imagen_huella || data.imagen_firma)) {
                    actualizarUIHuella(data);
                    // Si ya tenemos lo que buscábamos, paramos el polling
                    // Nota: Podríamos dejarlo si queremos capturar ambos, 
                    // pero usualmente se hace uno por uno.
                }
            }
        } catch (error) {
            console.error("Error en polling de huella:", error);
        }
    };

    // Primera consulta inmediata para evitar esperar el primer intervalo
    consultarHuellaUnaVez();
    pollingHuellaInterval = setInterval(consultarHuellaUnaVez, 3000);
}

function actualizarUIHuella(data) {
    if (!data) return;
    
    const imgHuella = document.getElementById('imgHuella');
    const imgFirma = document.getElementById('imgFirma');
    const estadoHuella = document.getElementById('estadoHuella');
    const estadoFirma = document.getElementById('estadoFirma');
    const btnVerHuella = document.getElementById('btnVerHuella');
    
    let baseUrl = API_BASE_URL.replace('/api', '');
    
    // Forzar refresco visual cuando backend devuelve misma ruta de archivo
    const versionToken = encodeURIComponent(data.fecha || Date.now());

    // Actualizar Huella
    if (imgHuella && data.imagen_huella) {
        const urlAbsoluta = data.imagen_huella.startsWith('http') ? data.imagen_huella : `${baseUrl}${data.imagen_huella}`;
        imgHuella.src = `${urlAbsoluta}${urlAbsoluta.includes('?') ? '&' : '?'}v=${versionToken}`;
        imgHuella.style.display = 'block';
        if (estadoHuella) estadoHuella.style.display = 'none';
        if (btnVerHuella) btnVerHuella.style.display = 'inline-block';
    } else if (imgHuella) {
        imgHuella.src = '';
        imgHuella.style.display = 'none';
        if (estadoHuella) {
            estadoHuella.innerHTML = 'No capturada';
            estadoHuella.style.display = 'block';
        }
        if (btnVerHuella) btnVerHuella.style.display = 'none';
    }

    // Actualizar Firma
    const previewFirmaImg = document.getElementById('preview-firma-img');
    const previewFirmaWrapper = document.getElementById('preview-firma-wrapper');
    const previewFirmaStatus = document.getElementById('preview-firma-status');

    if (imgFirma && data.imagen_firma) {
        const urlAbsolutaFirma = data.imagen_firma.startsWith('http') ? data.imagen_firma : `${baseUrl}${data.imagen_firma}`;
        imgFirma.src = `${urlAbsolutaFirma}${urlAbsolutaFirma.includes('?') ? '&' : '?'}v=${versionToken}`;
        imgFirma.style.display = 'block';
        if (estadoFirma) estadoFirma.style.display = 'none';
        
        // Sincronizar con Dashboard de Vista Previa
        if (previewFirmaStatus) {
            previewFirmaStatus.textContent = 'FIRMA: ✅';
            previewFirmaStatus.className = 'badge-tag badge-normal';
        }
        if (previewFirmaImg) {
            previewFirmaImg.src = `${urlAbsolutaFirma}${urlAbsolutaFirma.includes('?') ? '&' : '?'}v=${versionToken}`;
            if (previewFirmaWrapper) previewFirmaWrapper.style.display = 'block';
        }
    } else if (imgFirma) {
        imgFirma.src = '';
        imgFirma.style.display = 'none';
        if (estadoFirma) {
            estadoFirma.innerHTML = 'No capturada';
            estadoFirma.style.display = 'block';
        }

        if (previewFirmaStatus) {
            previewFirmaStatus.textContent = 'FIRMA: ❌';
            previewFirmaStatus.className = 'badge-tag badge-alert';
        }
        if (previewFirmaWrapper) previewFirmaWrapper.style.display = 'none';
    }

    // Sincronizar Huella con Dashboard de Vista Previa
    const previewHuellaStatus = document.getElementById('preview-huella-status');
    const previewHuellaImg = document.getElementById('preview-huella-img');
    const previewHuellaWrapper = document.getElementById('preview-huella-wrapper');

    if (previewHuellaStatus) {
        if (data.imagen_huella) {
            const urlAbsolutaHuella = data.imagen_huella.startsWith('http') ? data.imagen_huella : `${baseUrl}${data.imagen_huella}`;
            previewHuellaStatus.textContent = 'HUELLA: ✅';
            previewHuellaStatus.className = 'badge-tag badge-normal';
            if (previewHuellaImg) {
                previewHuellaImg.src = `${urlAbsolutaHuella}${urlAbsolutaHuella.includes('?') ? '&' : '?'}v=${versionToken}`;
                if (previewHuellaWrapper) previewHuellaWrapper.style.display = 'block';
            }
        } else {
            previewHuellaStatus.textContent = 'HUELLA: ❌';
            previewHuellaStatus.className = 'badge-tag badge-alert';
            if (previewHuellaWrapper) previewHuellaWrapper.style.display = 'none';
        }
    }
}

function abrirDetalleHuella() {
    const pacienteId = obtenerValorInput('paciente_id');
    if (!pacienteId) {
        mostrarMensaje("Seleccione un paciente primero", "error");
        return;
    }
    const baseUrlFrontend = window.location.origin;
    const url = `${baseUrlFrontend}/parto/huella/ver/${encodeURIComponent(pacienteId)}`;
    window.open(url, 'DetalleHuella', 'width=600,height=800,scrollbars=yes');
}

async function refrescarBiometriaAhora() {
    const pacienteId = obtenerValorInput('paciente_id');
    if (!pacienteId) {
        mostrarMensaje("Seleccione un paciente primero", "warning");
        return;
    }

    try {
        mostrarMensaje("Actualizando biometría...", "info");
        const baseUrl = API_BASE_URL;
        const response = await fetch(`${baseUrl}/huella/${pacienteId}/?_=${new Date().getTime()}`);
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const data = await response.json();
        actualizarUIHuella(data);

        if (data && (data.imagen_huella || data.imagen_firma)) {
            mostrarMensaje("✅ Biometría actualizada", "success");
        } else {
            mostrarMensaje("No hay nueva biometría para este paciente", "info");
        }
    } catch (error) {
        console.error("Error al refrescar biometría:", error);
        mostrarMensaje("Error al refrescar biometría", "error");
    }
}

async function activarCapturaTablet(tipo) {
    let pacienteId = obtenerValorInput('paciente_id');
    const formularioId = obtenerValorInput('formulario_id') || "";
    
    // Si no hay ID de paciente, intentar guardar el paciente primero (para pacientes nuevos)
    if (!pacienteId) {
        console.log("📝 Paciente nuevo detectado, intentando guardar antes de captura...");
        try {
            // Intentar guardar el paciente (esto validará nombres, identificación, etc.)
            const paciente = await guardarPaciente();
            if (paciente && paciente.id) {
                pacienteId = paciente.id;
                console.log("✅ Paciente guardado exitosamente con ID:", pacienteId);
            } else {
                console.error("❌ No se pudo obtener el ID del paciente tras guardar");
                return; // guardarPaciente ya muestra los mensajes de error
            }
        } catch (error) {
            console.error("❌ Error al guardar paciente previo a captura:", error);
            mostrarMensaje(error.message || "Guarde los datos del paciente primero.", "warning");
            return;
        }
    }

    if (tipo === 'huella') {
        mostrarMensaje("Iniciando captura de huella en la tablet...", "info");
        const estadoHuella = document.getElementById('estadoHuella');
        if (estadoHuella) {
            estadoHuella.innerHTML = '<div class="spinner-border spinner-border-sm text-primary" role="status"></div> Esperando huella...';
        }
        
        // Disparar Intent corregido para la App de Veneve/Fingerprint
        const intentUrl = `fingerprint://capture?paciente_id=${pacienteId}&formulario_id=${formularioId}`;
        console.log("🚀 Disparando captura de huella:", intentUrl);
        
        // Intentar abrir el deep link
        setTimeout(() => {
            window.location.href = intentUrl;
        }, 100);
        
        iniciarPollingHuella(pacienteId);
    }
}

// Globalizar
window.activarCapturaTablet = activarCapturaTablet;
window.abrirDetalleHuella = abrirDetalleHuella;
window.refrescarBiometriaAhora = refrescarBiometriaAhora;
window.iniciarPollingHuella = iniciarPollingHuella;
window.cerrarModalFirma = cerrarModalFirma;
window.limpiarFirma = limpiarFirma;
window.guardarFirmaDigital = guardarFirmaDigital;

