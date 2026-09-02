/**
 * MEOWS Form - Validación y Cálculo en Tiempo Real
 * Calcula scores, sumatoria y riesgo automáticamente mientras el usuario ingresa valores
 * Conectado al backend Django para obtener rangos desde la base de datos
 */

// Rangos MEOWS - se cargan desde el backend
let MEOWS_RANGOS = {};

function getMeowsUrl(key, fallback = '') {
    const urls = window.MEOWS_URLS || {};
    return urls[key] || fallback;
}

function getApiGuardarBiometriaUrl() {
    const explicit = getMeowsUrl('apiGuardarHuella', '');
    if (explicit) return explicit;
    const buscar = getMeowsUrl('apiBuscarPaciente', '/fetal/meows/api/buscar-paciente/');
    if (buscar.includes('/api/buscar-paciente/')) {
        return buscar.replace('/api/buscar-paciente/', '/api/save-biometrics/');
    }
    return '/fetal/meows/api/save-biometrics/';
}

function buildUrlFromTemplate(template, value, placeholder = '__PACIENTE_ID__') {
    if (!template) return '';
    const valor = encodeURIComponent(String(value ?? '').trim());
    if (!valor) return template;
    if (template.includes(placeholder)) {
        return template.replace(placeholder, valor);
    }
    // Plantillas construidas con ID 0 (rutas int)
    return template.replace('/0/', `/${valor}/`);
}

function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (const cookieRaw of cookies) {
            const cookie = cookieRaw.trim();
            if (cookie.startsWith(`${name}=`)) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}

// Control de alertas sonoras - evita repetir el sonido para la misma alerta
let alertasNotificadas = new Set();
let riesgoAnterior = null;

// Rangos fallback (por si falla la carga desde el backend)
const MEOWS_RANGOS_FALLBACK = {
    'fc': [
        { min: 0, max: 59, score: 3 },
        { min: 60, max: 110, score: 0 },
        { min: 111, max: 149, score: 2 },
        { min: 150, max: 999, score: 3 }
    ],
    'ta_sys': [
        { min: 0, max: 79, score: 3 },
        { min: 80, max: 89, score: 2 },
        { min: 90, max: 139, score: 0 },
        { min: 140, max: 149, score: 1 },
        { min: 150, max: 159, score: 2 },
        { min: 160, max: 999, score: 3 }
    ],
    'ta_dia': [
        { min: 0, max: 59, score: 0 },
        { min: 60, max: 89, score: 0 },
        { min: 90, max: 99, score: 1 },
        { min: 100, max: 109, score: 2 },
        { min: 110, max: 120, score: 3 },
        { min: 121, max: 999, score: 3 }
    ],
    'fr': [
        { min: 0, max: 4, score: 3 },
        { min: 5, max: 9, score: 3 },
        { min: 10, max: 17, score: 0 },
        { min: 18, max: 24, score: 1 },
        { min: 25, max: 29, score: 2 },
        { min: 30, max: 999, score: 3 }
    ],
    'temp': [
        { min: 0, max: 33.9, score: 3 },
        { min: 34.0, max: 35.0, score: 1 },
        { min: 35.1, max: 37.9, score: 0 },
        { min: 38.0, max: 38.9, score: 1 },
        { min: 39.0, max: 999, score: 3 }
    ],
    'spo2': [
        // % de O2 requerido para mantener Saturación > 95% (FiO2 suplementario), no SpO2 directo.
        { min: 0, max: 23, score: 0 },
        { min: 24, max: 39, score: 1 },
        { min: 40, max: 100, score: 3 }
    ],
    'glasgow': [
        { min: 0, max: 14, score: 3 },
        { min: 15, max: 15, score: 0 }
    ],
    'fcf': [
        { min: 0, max: 99, score: 3 },
        { min: 100, max: 109, score: 2 },
        { min: 110, max: 160, score: 0 },
        { min: 161, max: 180, score: 2 },
        { min: 181, max: 999, score: 3 }
    ]
};

// Mensajes de conducta por riesgo
const CONDUCTAS = {
    'BLANCO': 'RUTINA:  OBSERVACION -Minimo 12 horas de Observacion',
    'VERDE': 'RIESGO BAJO OBSERVACION: mínimo cada 4 horas. LLAMADO: Enfermera a cargo',
    'AMARILLO': 'RIESGO INTERMEDIO: OBSERVACION -Minnimo cada hora LLAMADO: Urgente al equipo medico al de la paciente con las competencias para manejo de la emergencia obstetrica',
    'ROJO': 'RIESGO ALTO: OBSERVACION Monitoreo continuo de signos vitales LLAMADO :Emergente al equipo con conpetencias en estado critico y habilidades para el diagnostico'
};

/**
 * Carga los rangos MEOWS desde el backend Django
 */
async function cargarRangosDesdeBackend() {
    try {
        const response = await fetch(getMeowsUrl('apiRangos', '/api/rangos/'));
        if (response.ok) {
            const rangos = await response.json();
            MEOWS_RANGOS = rangos;
            console.log('✅ Rangos MEOWS cargados desde el backend:', Object.keys(rangos).length, 'parámetros');
            return true;
        } else {
            console.warn('⚠️ No se pudieron cargar rangos desde el backend, usando fallback');
            MEOWS_RANGOS = MEOWS_RANGOS_FALLBACK;
            return false;
        }
    } catch (error) {
        console.error('❌ Error al cargar rangos desde el backend:', error);
        console.warn('⚠️ Usando rangos fallback');
        MEOWS_RANGOS = MEOWS_RANGOS_FALLBACK;
        return false;
    }
}

/**
 * Calcula el score MEOWS para un parámetro y valor dado
 */
function calcularScore(parametro, valor) {
    if (!valor || valor === '') return null;

    const valorNum = parseFloat(valor);
    if (isNaN(valorNum)) return null;

    // Validación especial para temperatura: valores fuera de 34-40 no tienen score
    if (parametro === 'temp') {
        if (valorNum < 34 || valorNum > 40) {
            return null; // Retorna null para indicar que está fuera de rango válido
        }
    }

    // Validación especial para frecuencia cardíaca
    if (parametro === 'fc') {
        // Valores fuera de 40-170 no tienen score
        if (valorNum < 40 || valorNum > 170) {
            return null; // Retorna null para indicar que está fuera de rango válido
        }
        // El score en sí (incluido >=150 -> rojo) ya lo resuelve MEOWS_RANGOS.fc más abajo.
    }

    // Validación especial para frecuencia cardíaca fetal: solo se descartan valores
    // fisiológicamente imposibles (error de digitación). Los valores de bradicardia/
    // taquicardia real (fuera de 110-160) SÍ deben puntuar según MEOWS_RANGOS.
    if (parametro === 'fcf') {
        if (valorNum < 30 || valorNum > 300) {
            return null; // Retorna null para indicar que está fuera de rango válido
        }
    }

    const rangos = MEOWS_RANGOS[parametro];
    if (!rangos) return null;

    for (const rango of rangos) {
        if (valorNum >= rango.min && valorNum <= rango.max) {
            return rango.score;
        }
    }

    return null;
}

/**
 * Calcula score consultando la API y usa fallback local
 * si hay error de red o respuesta inválida.
 */
async function calcularScoreDesdeApi(parametro, valor) {
    if (!valor || valor === '') return null;

    const urlApi = getMeowsUrl('apiCalcularScore', '/api/calcular-score/');
    try {
        const response = await fetch(urlApi, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken') || ''
            },
            body: JSON.stringify({
                parametro: parametro,
                valor: valor
            })
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const data = await response.json();
        if (data && data.success) {
            return data.score;
        }
    } catch (error) {
        console.warn('⚠️ Falló cálculo por API, usando cálculo local:', error);
    }

    return calcularScore(parametro, valor);
}

/**
 * Actualiza el feedback visual de un parámetro
 */
function actualizarFeedback(parametro, valor, score) {
    const input = document.getElementById(parametro);
    const scoreElement = document.getElementById(`score-${parametro}`);
    const fillElement = document.getElementById(`fill-${parametro}`);
    const messageElement = document.getElementById(`message-${parametro}`);
    const card = input.closest('.parameter-card');

    // Limpiar clases anteriores
    input.classList.remove('score-0', 'score-1', 'score-2', 'score-3');
    scoreElement.classList.remove('score-0', 'score-1', 'score-2', 'score-3');
    fillElement.classList.remove('score-0', 'score-1', 'score-2', 'score-3');
    messageElement.classList.remove('error', 'success', 'warning', 'success-green', 'error-purple');
    if (card) {
        card.classList.remove('card-score-0', 'card-score-1', 'card-score-2', 'card-score-3');
    }
    messageElement.textContent = '';

    if (score === null) {
        if (valor && valor !== '') {
            // Validación especial para temperatura
            if (parametro === 'temp') {
                const valorNum = parseFloat(valor);
                if (!isNaN(valorNum)) {
                    if (valorNum < 34 || valorNum > 40) {
                        messageElement.textContent = 'Dato fuera de rango';
                        messageElement.classList.add('error', 'error-purple');
                        return;
                    }
                }
            }
            // Para otros parámetros, mensaje genérico
            messageElement.textContent = 'Valor fuera de rango';
            messageElement.classList.add('error');
        }
        return;
    }

    // Aplicar clases de score
    input.classList.add(`score-${score}`);
    scoreElement.textContent = score;
    scoreElement.classList.add(`score-${score}`);
    fillElement.classList.add(`score-${score}`);
    if (card) {
        card.classList.add(`card-score-${score}`);
    }

    // Mensaje según score
    if (score === 0) {
        messageElement.textContent = '✓ Normal';
        messageElement.classList.add('success');
    } else if (score === 1) {
        messageElement.textContent = '⚠ Moderado';
        messageElement.classList.add('success-green');
    } else if (score === 2) {
        messageElement.textContent = '⚠⚠ Moderado-Alto';
        messageElement.classList.add('warning');
    } else if (score === 3) {
        messageElement.textContent = '🚨 CRÍTICO';
        messageElement.classList.add('error');
    }
}

/**
 * Reproduce el sonido de alerta suave si corresponde
 * Solo reproduce cuando:
 * - El riesgo es ALTO (ROJO)
 * - Es una nueva alerta (no se ha notificado antes)
 * - El riesgo cambió de otro nivel a ROJO
 */
function reproducirSonidoSiCorresponde(riesgoActual, riesgoAnterior) {
    // Crear un ID único para esta combinación de riesgo
    const alertaId = `riesgo-${riesgoActual}-${Date.now()}`;

    // Solo reproducir si:
    // 1. El riesgo actual es ROJO (RIESGO ALTO)
    // 2. No es el mismo riesgo que el anterior (es una nueva alerta)
    // 3. No se ha notificado antes (prevención adicional)
    if (riesgoActual === 'ROJO' && riesgoActual !== riesgoAnterior && !alertasNotificadas.has(alertaId)) {
        const alertSound = document.getElementById('alertSound');
        if (alertSound) {
            // Intentar reproducir el sonido
            alertSound.play().catch(error => {
                // Si falla la reproducción (por políticas del navegador), solo loguear
                console.warn('No se pudo reproducir la alerta sonora:', error);
            });

            // Marcar esta alerta como notificada
            alertasNotificadas.add(alertaId);

            // Limpiar alertas antiguas del Set para evitar acumulación (mantener solo las últimas 10)
            if (alertasNotificadas.size > 10) {
                const firstKey = alertasNotificadas.values().next().value;
                alertasNotificadas.delete(firstKey);
            }

            console.log('🔊 Alerta sonora activada: RIESGO ALTO detectado');
        }
    }
}

/**
 * Selector práctico de hora (12h + AM/PM) para el monitoreo.
 * Reemplaza el <input type="time"> nativo -cuyo formato AM/PM depende del
 * idioma del sistema operativo del usuario- por tres selects explícitos,
 * y mantiene sincronizado un input oculto en formato 24h (HH:MM) que es
 * el que espera el backend.
 */
function poblarSelectHorasMonitoreo() {
    const sel = document.getElementById('hora_monitoreo_horas');
    if (!sel) return;
    sel.innerHTML = '';
    for (let h = 1; h <= 12; h++) {
        const opt = document.createElement('option');
        opt.value = String(h).padStart(2, '0');
        opt.textContent = String(h).padStart(2, '0');
        sel.appendChild(opt);
    }
}

function poblarSelectMinutosMonitoreo() {
    const sel = document.getElementById('hora_monitoreo_minutos');
    if (!sel) return;
    sel.innerHTML = '';
    for (let m = 0; m < 60; m++) {
        const opt = document.createElement('option');
        opt.value = String(m).padStart(2, '0');
        opt.textContent = String(m).padStart(2, '0');
        sel.appendChild(opt);
    }
}

function actualizarHoraMonitoreoOculta() {
    const horasSel = document.getElementById('hora_monitoreo_horas');
    const minutosSel = document.getElementById('hora_monitoreo_minutos');
    const periodoSel = document.getElementById('hora_monitoreo_periodo');
    const hiddenInput = document.getElementById('hora_monitoreo');
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

    validarFechaHoraMonitoreo();
}

function inicializarSelectorHoraMonitoreo() {
    const horasSel = document.getElementById('hora_monitoreo_horas');
    const minutosSel = document.getElementById('hora_monitoreo_minutos');
    const periodoSel = document.getElementById('hora_monitoreo_periodo');
    if (!horasSel || !minutosSel || !periodoSel) return;

    poblarSelectHorasMonitoreo();
    poblarSelectMinutosMonitoreo();

    // Punto de partida: la hora actual, salvo que se esté editando una
    // medición existente (window.MEOWS_HORA_INICIAL, fijado por
    // formulario.html en formato 24h "HH:MM"), en cuyo caso se preselecciona
    // la hora ya guardada para poder corregirla.
    let horas24Actual, minutosActual;
    if (window.MEOWS_HORA_INICIAL) {
        const [h, m] = window.MEOWS_HORA_INICIAL.split(':');
        horas24Actual = parseInt(h, 10);
        minutosActual = parseInt(m, 10);
    } else {
        const ahora = new Date();
        horas24Actual = ahora.getHours();
        minutosActual = ahora.getMinutes();
    }
    let horas12Actual = horas24Actual % 12;
    if (horas12Actual === 0) horas12Actual = 12;

    horasSel.value = String(horas12Actual).padStart(2, '0');
    minutosSel.value = String(minutosActual).padStart(2, '0');
    periodoSel.value = horas24Actual >= 12 ? 'PM' : 'AM';

    actualizarHoraMonitoreoOculta();

    horasSel.addEventListener('change', actualizarHoraMonitoreoOculta);
    minutosSel.addEventListener('change', actualizarHoraMonitoreoOculta);
    periodoSel.addEventListener('change', actualizarHoraMonitoreoOculta);
}

/**
 * Valida que la fecha/hora de monitoreo ingresada manualmente esté completa
 * y tenga un formato válido. Sin restricción de rango.
 */
function validarFechaHoraMonitoreo() {
    const fechaInput = document.getElementById('fecha_monitoreo');
    const horaInput = document.getElementById('hora_monitoreo');
    const mensajeEl = document.getElementById('message-hora_monitoreo');
    if (!fechaInput || !horaInput) return true;

    const fechaVal = fechaInput.value;
    const horaVal = horaInput.value;

    if (mensajeEl) {
        mensajeEl.textContent = '';
        mensajeEl.classList.remove('error', 'success');
    }

    if (!fechaVal || !horaVal) {
        return false;
    }

    const fechaHora = new Date(`${fechaVal}T${horaVal}:00`);
    if (isNaN(fechaHora.getTime())) {
        if (mensajeEl) {
            mensajeEl.textContent = 'Fecha u hora inválida';
            mensajeEl.classList.add('error');
        }
        horaInput.setCustomValidity('Fecha u hora inválida');
        return false;
    }

    horaInput.setCustomValidity('');
    return true;
}

/**
 * Calcula y actualiza el resumen total
 */
function actualizarResumen() {
    const inputs = document.querySelectorAll('.parameter-input');
    let total = 0;
    const scores = {};

    inputs.forEach(input => {
        const parametro = input.dataset.param;
        const valor = input.value;
        const score = calcularScore(parametro, valor);

        if (score !== null) {
            scores[parametro] = score;
            total += score;
        }
    });

    // Actualizar total
    const totalElement = document.getElementById('total-score');
    totalElement.textContent = total;

    // Obtener el contenedor summary-item padre
    const summaryItem = totalElement.closest('.summary-item');

    // Remover clases de color anteriores del elemento y del contenedor
    totalElement.classList.remove('score-verde', 'score-amarillo', 'score-rojo', 'score-blanco');
    if (summaryItem) {
        summaryItem.classList.remove('item-score-verde', 'item-score-amarillo', 'item-score-rojo', 'item-score-blanco');
    }

    // Calcular riesgo y aplicar color al puntaje según el MISMO criterio que el backend
    // (meows/services/meows.py::clasificar_riesgo):
    // - Total >= 6 → ROJO (RIESGO ALTO)
    // - Total 4 a 5, o cualquier parámetro individual con puntaje 3 → AMARILLO (RIESGO INTERMEDIO)
    // - Total = 0 (sin parámetro crítico) → BLANCO
    // - Total 1 a 3 (sin parámetro crítico) → VERDE (RIESGO BAJO)
    const tieneParametroCritico = Object.values(scores).some(s => s === 3);
    let riesgo = 'VERDE';

    if (total >= 6) {
        riesgo = 'ROJO';
        totalElement.classList.add('score-rojo');
        if (summaryItem) summaryItem.classList.add('item-score-rojo');
    } else if (total >= 4 || tieneParametroCritico) {
        riesgo = 'AMARILLO';
        totalElement.classList.add('score-amarillo');
        if (summaryItem) summaryItem.classList.add('item-score-amarillo');
    } else if (total === 0) {
        riesgo = 'BLANCO';
        totalElement.classList.add('score-blanco');
        if (summaryItem) summaryItem.classList.add('item-score-blanco');
    } else {
        // total >= 1 && total <= 3, sin parámetro crítico
        riesgo = 'VERDE';
        totalElement.classList.add('score-verde');
        if (summaryItem) summaryItem.classList.add('item-score-verde');
    }

    // Reproducir sonido si corresponde (antes de actualizar el riesgo anterior)
    reproducirSonidoSiCorresponde(riesgo, riesgoAnterior);

    // Actualizar el riesgo anterior para la próxima comparación
    riesgoAnterior = riesgo;

    // Actualizar badge de riesgo
    const riskElement = document.getElementById('risk-level');
    riskElement.innerHTML = `<span class="risk-badge risk-${riesgo.toLowerCase()}">${riesgo}</span>`;

    // Actualizar conducta
    const conductaElement = document.getElementById('conducta-text');
    conductaElement.textContent = CONDUCTAS[riesgo];

    // Obtener el summary-item que contiene la conducta y aplicar la clase de color
    const conductaSummaryItem = conductaElement.closest('.summary-item');
    if (conductaSummaryItem) {
        // Remover clases anteriores
        conductaSummaryItem.classList.remove('item-score-verde', 'item-score-amarillo', 'item-score-rojo', 'item-score-blanco');
        // Aplicar la clase correspondiente al riesgo
        if (riesgo === 'BLANCO') {
            conductaSummaryItem.classList.add('item-score-blanco');
        } else if (riesgo === 'VERDE') {
            conductaSummaryItem.classList.add('item-score-verde');
        } else if (riesgo === 'AMARILLO') {
            conductaSummaryItem.classList.add('item-score-amarillo');
        } else if (riesgo === 'ROJO') {
            conductaSummaryItem.classList.add('item-score-rojo');
        }
    }
}

/**
 * Busca los datos del paciente en el endpoint unificado (compartido con Monitoreo Fetal
 * y Trabajo de Parto) al ingresar el número de documento, y autocompleta nombre, fecha de
 * nacimiento, edad, aseguradora, cama y fecha de ingreso — evitando volver a digitarlos.
 */
let ultimoDocBuscadoMeows = null;

async function buscarPacienteUnificadoMeows() {
    const docInput = document.getElementById('numero_documento');
    if (!docInput) return;
    const doc = docInput.value.trim();
    if (!doc || doc === ultimoDocBuscadoMeows) return;
    ultimoDocBuscadoMeows = doc;

    try {
        const response = await fetch(`/atencion/api/datos-paciente-unificado/?doc=${encodeURIComponent(doc)}`, {
            credentials: 'same-origin'
        });
        if (!response.ok) return;
        const data = await response.json();
        if (!data.ok || !data.encontrado) return;

        const setCampo = (id, valor) => {
            const el = document.getElementById(id);
            if (!el || valor === null || valor === undefined || valor === '') return;
            el.value = valor;
            el.dispatchEvent(new Event('change', { bubbles: true }));
        };

        setCampo('nombre_completo', data.nombre_completo);
        setCampo('fecha_nacimiento', data.fecha_nacimiento);
        setCampo('edad', data.edad);
        setCampo('aseguradora', data.aseguradora);
        setCampo('cama', data.cama);
        setCampo('fecha_ingreso', data.fecha_ingreso);
    } catch (error) {
        console.error('Error al buscar datos unificados del paciente:', error);
    }
}

/**
 * Sincroniza los campos del paciente con los campos ocultos del formulario MEOWS
 */
function sincronizarCamposPaciente() {
    const campos = [
        'nombre_completo', 'numero_documento', 'fecha_nacimiento',
        'edad', 'aseguradora', 'cama', 'fecha_ingreso', 'responsable'
    ];

    campos.forEach(campo => {
        const input = document.getElementById(campo);
        const hidden = document.getElementById(`hidden-${campo}`);
        if (input && hidden) {
            // Sincronizar al cambiar
            input.addEventListener('input', function () {
                hidden.value = this.value;
            });
            input.addEventListener('change', function () {
                hidden.value = this.value;
            });
            // Sincronizar valor inicial
            hidden.value = input.value;
        }
    });
}

function actualizarVistaFirmaPaciente(imagenFirmaUrl, estadoTexto = "Firma registrada") {
    const firmaImg = document.getElementById("imgFirma");
    const firmaContainer = document.getElementById("firma-container-preview");
    const firmaEstado = document.getElementById("estadoFirma");

    if (!imagenFirmaUrl) {
        if (firmaContainer) firmaContainer.style.display = "none";
        if (firmaEstado) {
            firmaEstado.textContent = "Sin firmar";
            firmaEstado.style.color = "";
            firmaEstado.style.background = "";
        }
        return;
    }

    const timestampedUrl = `${imagenFirmaUrl}?t=${Date.now()}`;
    if (firmaImg) {
        firmaImg.src = timestampedUrl;
        firmaImg.style.setProperty('display', 'block', 'important');
    }
    if (firmaContainer) {
        firmaContainer.style.setProperty('display', 'flex', 'important');
        firmaContainer.classList.add('is-visible');
    }
    if (firmaEstado) {
        firmaEstado.textContent = estadoTexto;
        firmaEstado.style.color = "#27ae60";
        firmaEstado.style.background = "#e8f5e9";
    }

}

async function refrescarFirmaPaciente(documento, opts = {}) {
    const { silencioso = true, estado = "Firma registrada" } = opts;
    const pacienteDoc = (documento || '').trim();
    if (!pacienteDoc) return false;

    const btnRefrescar = document.getElementById('btn-refrescar-firma');
    const originalText = btnRefrescar ? btnRefrescar.innerHTML : '';
    if (btnRefrescar) {
        btnRefrescar.disabled = true;
        btnRefrescar.innerHTML = '<span class="btn-icon">⏳</span>Actualizando...';
    }

    try {
        // No dependemos del endpoint de huella: obtenemos solo la firma desde búsqueda de paciente.
        const apiBuscar = getMeowsUrl('apiBuscarPaciente', '/api/buscar-paciente/');
        const response = await fetch(`${apiBuscar}?documento=${encodeURIComponent(pacienteDoc)}&t=${Date.now()}`, {
            method: 'GET',
            headers: { 'Accept': 'application/json' },
            credentials: 'same-origin',
        });

        if (!response.ok) {
            actualizarVistaFirmaPaciente(null);
            if (!silencioso) alert("No hay firma guardada para este paciente.");
            return false;
        }

        const data = await response.json();
        const firmaUrl = data?.paciente?.biometria?.imagen_firma || null;
        if (data.success && firmaUrl) {
            actualizarVistaFirmaPaciente(firmaUrl, estado);
            return true;
        }

        actualizarVistaFirmaPaciente(null);
        if (!silencioso) alert("No hay firma guardada para este paciente.");
        return false;
    } catch (error) {
        if (!silencioso) alert("No fue posible refrescar la firma. Intente nuevamente.");
        return false;
    } finally {
        if (btnRefrescar) {
            btnRefrescar.disabled = false;
            btnRefrescar.innerHTML = originalText;
        }
    }
}

/**
 * Calcula la edad a partir de la fecha de nacimiento
 */
function calcularEdad(fechaNacimiento) {
    if (!fechaNacimiento) return '';
    const hoy = new Date();
    const nacimiento = new Date(fechaNacimiento);
    let edad = hoy.getFullYear() - nacimiento.getFullYear();
    const mes = hoy.getMonth() - nacimiento.getMonth();

    if (mes < 0 || (mes === 0 && hoy.getDate() < nacimiento.getDate())) {
        edad--;
    }
    return edad >= 0 ? edad : '';
}

/**
 * Obtiene el ID del paciente disponible en la vista actual
 */
function obtenerPacienteIdActual() {
    // 1) Prioridad: botón de historial ya sincronizado con el paciente activo
    const btnHistorial = document.getElementById('btn-ver-historial');
    if (btnHistorial && btnHistorial.href) {
        const matchHistorial = btnHistorial.href.match(/\/historial\/(\d+)\/?/);
        if (matchHistorial) return matchHistorial[1];
    }

    // 2) Fallback: URL actual /nuevo/<id>/
    const matchPath = window.location.pathname.match(/\/nuevo\/(\d+)\/?/);
    if (matchPath) return matchPath[1];

    return null;
}

// Event listener para calcular edad cuando cambia fecha de nacimiento
document.addEventListener('DOMContentLoaded', function () {
    const fechaNacInput = document.getElementById('fecha_nacimiento');
    const edadInput = document.getElementById('edad');

    if (fechaNacInput && edadInput) {
        fechaNacInput.addEventListener('change', function () {
            const edad = calcularEdad(this.value);
            edadInput.value = edad;
            // Disparar evento change para sincronizar campos ocultos
            edadInput.dispatchEvent(new Event('change'));
        });
    }
});

/**
 * Convierte el input de temperatura a select con valores válidos (34-40)
 */
function convertirTempASelect() {
    const tempInput = document.getElementById('temp');
    if (!tempInput || tempInput.tagName === 'SELECT') {
        return; // Ya es select o no existe
    }

    const valorActual = tempInput.value;
    const unidad = tempInput.dataset.unidad || '°C';

    // Generar opciones desde 34 hasta 40 con incrementos de 1 (valores enteros)
    let opciones = '<option value="">seleccione</option>';
    for (let valor = 34; valor <= 40; valor++) {
        opciones += `<option value="${valor}">${valor}</option>`;
    }

    // Crear el select
    const select = document.createElement('select');
    select.id = tempInput.id;
    select.name = tempInput.name;
    select.className = tempInput.className + ' parameter-select';
    select.required = tempInput.required;
    select.setAttribute('data-param', 'temp');
    select.setAttribute('data-unidad', unidad);
    select.innerHTML = opciones;

    // Seleccionar el valor actual si existe y está en el rango válido
    if (valorActual) {
        const valorNum = parseFloat(valorActual);
        if (!isNaN(valorNum) && valorNum >= 34 && valorNum <= 40) {
            // Redondear al entero más cercano
            select.value = Math.round(valorNum).toString();
        }
    }

    // Reemplazar el input con el select
    tempInput.parentNode.replaceChild(select, tempInput);
}

/**
 * Convierte el input de tensión arterial sistólica a select con valores válidos (70-200, de 10 en 10)
 */
function convertirTaSysASelect() {
    const taSysInput = document.getElementById('ta_sys');
    if (!taSysInput || taSysInput.tagName === 'SELECT') {
        return; // Ya es select o no existe
    }

    const valorActual = taSysInput.value;
    const unidad = taSysInput.dataset.unidad || 'mmHg';

    // Generar opciones desde 70 hasta 200 con incrementos de 10
    let opciones = '<option value="">seleccione</option>';
    for (let valor = 70; valor <= 200; valor += 10) {
        opciones += `<option value="${valor}">${valor}</option>`;
    }

    // Crear el select
    const select = document.createElement('select');
    select.id = taSysInput.id;
    select.name = taSysInput.name;
    select.className = taSysInput.className + ' parameter-select';
    select.required = taSysInput.required;
    select.setAttribute('data-param', 'ta_sys');
    select.setAttribute('data-unidad', unidad);
    select.innerHTML = opciones;

    // Seleccionar el valor actual si existe y está en el rango válido
    if (valorActual) {
        const valorNum = parseFloat(valorActual);
        if (!isNaN(valorNum) && valorNum >= 70 && valorNum <= 200) {
            // Redondear al múltiplo de 10 más cercano
            const valorRedondeado = Math.round(valorNum / 10) * 10;
            if (valorRedondeado >= 70 && valorRedondeado <= 200) {
                select.value = valorRedondeado.toString();
            }
        }
    }

    // Reemplazar el input con el select
    taSysInput.parentNode.replaceChild(select, taSysInput);
}

/**
 * Convierte el input de tensión arterial diastólica a select con valores válidos (60-120, de 10 en 10)
 */
function convertirTaDiaASelect() {
    const taDiaInput = document.getElementById('ta_dia');
    if (!taDiaInput || taDiaInput.tagName === 'SELECT') {
        return; // Ya es select o no existe
    }

    const valorActual = taDiaInput.value;
    const unidad = taDiaInput.dataset.unidad || 'mmHg';

    // Generar opciones desde 60 hasta 120 con incrementos de 10
    let opciones = '<option value="">seleccione</option>';
    for (let valor = 60; valor <= 120; valor += 10) {
        opciones += `<option value="${valor}">${valor}</option>`;
    }

    // Crear el select
    const select = document.createElement('select');
    select.id = taDiaInput.id;
    select.name = taDiaInput.name;
    select.className = taDiaInput.className + ' parameter-select';
    select.required = taDiaInput.required;
    select.setAttribute('data-param', 'ta_dia');
    select.setAttribute('data-unidad', unidad);
    select.innerHTML = opciones;

    // Seleccionar el valor actual si existe y está en el rango válido
    if (valorActual) {
        const valorNum = parseFloat(valorActual);
        if (!isNaN(valorNum) && valorNum >= 60 && valorNum <= 120) {
            // Redondear al múltiplo de 10 más cercano
            const valorRedondeado = Math.round(valorNum / 10) * 10;
            if (valorRedondeado >= 60 && valorRedondeado <= 120) {
                select.value = valorRedondeado.toString();
            }
        }
    }

    // Reemplazar el input con el select
    taDiaInput.parentNode.replaceChild(select, taDiaInput);
}

/**
 * Convierte el input de frecuencia cardíaca a select con valores válidos (40-170, de 10 en 10)
 */
function convertirFcASelect() {
    const fcInput = document.getElementById('fc');
    if (!fcInput || fcInput.tagName === 'SELECT') {
        return; // Ya es select o no existe
    }

    const valorActual = fcInput.value;
    const unidad = fcInput.dataset.unidad || 'lpm';

    // Generar opciones desde 40 hasta 170 con incrementos de 10
    let opciones = '<option value="">seleccione</option>';
    for (let valor = 40; valor <= 170; valor += 10) {
        opciones += `<option value="${valor}">${valor}</option>`;
    }

    // Crear el select
    const select = document.createElement('select');
    select.id = fcInput.id;
    select.name = fcInput.name;
    select.className = fcInput.className + ' parameter-select';
    select.required = fcInput.required;
    select.setAttribute('data-param', 'fc');
    select.setAttribute('data-unidad', unidad);
    select.innerHTML = opciones;

    // Seleccionar el valor actual si existe y está en el rango válido
    if (valorActual) {
        const valorNum = parseFloat(valorActual);
        if (!isNaN(valorNum) && valorNum >= 40 && valorNum <= 170) {
            // Redondear al múltiplo de 10 más cercano
            const valorRedondeado = Math.round(valorNum / 10) * 10;
            if (valorRedondeado >= 40 && valorRedondeado <= 170) {
                select.value = valorRedondeado.toString();
            }
        }
    }

    // Reemplazar el input con el select
    fcInput.parentNode.replaceChild(select, fcInput);
}

/**
 * Convierte el input de frecuencia cardíaca fetal a select con valores válidos (110-190, de 10 en 10)
 */
function convertirFcfASelect() {
    const fcfInput = document.getElementById('fcf');
    if (!fcfInput || fcfInput.tagName === 'SELECT') {
        return; // Ya es select o no existe
    }

    const valorActual = fcfInput.value;
    const unidad = fcfInput.dataset.unidad || 'lpm';

    // Generar opciones desde 110 hasta 190 con incrementos de 10
    let opciones = '<option value="">seleccione</option>';
    for (let valor = 110; valor <= 190; valor += 10) {
        opciones += `<option value="${valor}">${valor}</option>`;
    }

    // Crear el select
    const select = document.createElement('select');
    select.id = fcfInput.id;
    select.name = fcfInput.name;
    select.className = fcfInput.className + ' parameter-select';
    select.required = fcfInput.required;
    select.setAttribute('data-param', 'fcf');
    select.setAttribute('data-unidad', unidad);
    select.innerHTML = opciones;

    // Seleccionar el valor actual si existe y está en el rango válido
    if (valorActual) {
        const valorNum = parseFloat(valorActual);
        if (!isNaN(valorNum) && valorNum >= 110 && valorNum <= 190) {
            // Redondear al múltiplo de 10 más cercano
            const valorRedondeado = Math.round(valorNum / 10) * 10;
            if (valorRedondeado >= 110 && valorRedondeado <= 190) {
                select.value = valorRedondeado.toString();
            }
        }
    }

    // Reemplazar el input con el select
    fcfInput.parentNode.replaceChild(select, fcfInput);
}

/**
 * Convierte el input de SpO2 a select con los valores de % de O2 requerido
 * para mantener Saturación > 95% (FiO2 suplementario) — tal cual la tabla
 * oficial MEOWS, NO el valor de SpO2 del oxímetro. Ver el comentario en
 * MEOWS_RANGOS_FALLBACK.spo2 más arriba y meows/services/dinamica_signos_vitales.py.
 */
const OPCIONES_SPO2 = [21, 24, 28, 31, 35, 40, 50, 60, 80, 100];

function convertirSpo2ASelect() {
    const spo2Input = document.getElementById('spo2');
    if (!spo2Input || spo2Input.tagName === 'SELECT') {
        return; // Ya es select o no existe
    }

    const valorActual = spo2Input.value;
    const unidad = spo2Input.dataset.unidad || '%';

    let opciones = '<option value="">seleccione</option>';
    OPCIONES_SPO2.forEach((valor) => {
        const etiqueta = valor === 21 ? `${valor} (Aire ambiente)` : `${valor}`;
        opciones += `<option value="${valor}">${etiqueta}</option>`;
    });

    // Crear el select
    const select = document.createElement('select');
    select.id = spo2Input.id;
    select.name = spo2Input.name;
    select.className = spo2Input.className + ' parameter-select';
    select.required = spo2Input.required;
    select.setAttribute('data-param', 'spo2');
    select.setAttribute('data-unidad', unidad);
    select.innerHTML = opciones;

    // Seleccionar la opción más cercana al valor actual, si existe
    if (valorActual) {
        const valorNum = parseFloat(valorActual);
        if (!isNaN(valorNum)) {
            const masCercano = OPCIONES_SPO2.reduce((a, b) =>
                Math.abs(b - valorNum) < Math.abs(a - valorNum) ? b : a
            );
            select.value = masCercano.toString();
        }
    }

    // Reemplazar el input con el select
    spo2Input.parentNode.replaceChild(select, spo2Input);
}

/**
 * CLASE PARA MANEJO DE FIRMA DIGITAL
 */
class FirmaDigital {
    constructor(canvasId) {
        this.canvas = document.getElementById(canvasId);
        if (!this.canvas) return;
        this.ctx = this.canvas.getContext('2d');
        this.dibujando = false;
        this.hayFirma = false;
        
        // Ajustar resolución para pantallas retina
        const ratio = window.devicePixelRatio || 1;
        this.canvas.width = 400 * ratio;
        this.canvas.height = 200 * ratio;
        this.ctx.scale(ratio, ratio);
        
        this.ctx.lineWidth = 2;
        this.ctx.lineJoin = 'round';
        this.ctx.lineCap = 'round';
        this.ctx.strokeStyle = '#182848';

        this.initEvents();
    }

    initEvents() {
        const getPos = (e) => {
            const rect = this.canvas.getBoundingClientRect();
            const clientX = e.touches ? e.touches[0].clientX : e.clientX;
            const clientY = e.touches ? e.touches[0].clientY : e.clientY;
            
            // Factor de escala entre el tamaño visual (rect) y el lógico (400x200)
            const scaleX = 400 / rect.width;
            const scaleY = 200 / rect.height;
            
            return {
                x: (clientX - rect.left) * scaleX,
                y: (clientY - rect.top) * scaleY
            };
        };

        const start = (e) => {
            this.dibujando = true;
            this.hayFirma = true;
            const pos = getPos(e);
            this.ctx.beginPath();
            this.ctx.moveTo(pos.x, pos.y);
            e.preventDefault();
        };

        const move = (e) => {
            if (!this.dibujando) return;
            const pos = getPos(e);
            this.ctx.lineTo(pos.x, pos.y);
            this.ctx.stroke();
            e.preventDefault();
        };

        const stop = () => {
            this.dibujando = false;
        };

        this.canvas.addEventListener('mousedown', start);
        this.canvas.addEventListener('mousemove', move);
        window.addEventListener('mouseup', stop);

        this.canvas.addEventListener('touchstart', start, { passive: false });
        this.canvas.addEventListener('touchmove', move, { passive: false });
        this.canvas.addEventListener('touchend', stop);
    }

    limpiar() {
        this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
        this.hayFirma = false;
    }

    obtenerBase64() {
        if (!this.hayFirma) return null;
        return this.canvas.toDataURL('image/png');
    }
}

let firmaPad = null;

/**
 * Lanza el modal de biometría en lugar del deep link directo
 * AHORA: Se comporta como un popover posicionado sobre el botón
 */
function abrirModalBiometria() {
    const pacienteDoc = document.getElementById("numero_documento").value;
    if (!pacienteDoc) {
        alert("Por favor, ingrese el número de documento del paciente.");
        return;
    }

    const btnTrigger = document.getElementById('btn-capturar-huella');
    const modal = document.getElementById('modal-biometria');
    
    if (!btnTrigger || !modal) return;

    // Activar modo popover
    modal.classList.add('is-popover');
    
    // Calcular posición
    const rect = btnTrigger.getBoundingClientRect();
    const scrollLeft = window.pageXOffset || document.documentElement.scrollLeft;
    const scrollTop = window.pageYOffset || document.documentElement.scrollTop;
    
    // Posicionar encima del botón (850px es el ancho en el CSS)
    const popoverWidth = 850;
    let left = rect.left + scrollLeft - (popoverWidth / 2) + (rect.width / 2);
    let top = rect.top + scrollTop - 480; // Ajuste para que quede arriba del botón
    
    // Validar bordes de pantalla
    if (left < 10) left = 10;
    if (left + popoverWidth > window.innerWidth - 10) {
        left = window.innerWidth - popoverWidth - 10;
    }
    if (top < 10) top = rect.bottom + scrollTop + 20; // Si no cabe arriba, poner abajo

    modal.style.left = `${left}px`;
    modal.style.top = `${top}px`;
    modal.style.display = 'block';
    
    // Inicializar Firma si no existe
    if (!firmaPad) {
        firmaPad = new FirmaDigital('firma-canvas');
    } else {
        firmaPad.limpiar();
    }

    // Limpiar previews de huella en el modal
    const preview = document.getElementById('huella-modal-preview');
    const status = document.getElementById('huella-modal-status');
    if (preview) preview.innerHTML = '<span class="placeholder-icon">🖱️</span>';
    if (status) status.innerHTML = 'Esperando captura...';

    // Cerrar al hacer clic fuera
    const closeOnOutsideClick = (e) => {
        if (!modal.contains(e.target) && e.target !== btnTrigger && !btnTrigger.contains(e.target)) {
            modal.style.display = 'none';
            document.removeEventListener('mousedown', closeOnOutsideClick);
        }
    };
    
    setTimeout(() => {
        document.addEventListener('mousedown', closeOnOutsideClick);
    }, 100);
}

/**
 * Guarda la firma digital vía API
 */
async function guardarFirmaDigital() {
    const b64 = firmaPad.obtenerBase64();
    if (!b64) {
        alert("Por favor, el paciente debe firmar primero.");
        return;
    }

    const pacienteDoc = document.getElementById("numero_documento").value;
    const btn = document.getElementById('btn-guardar-firma');
    const originalText = btn.innerHTML;
    
    btn.disabled = true;
    btn.innerHTML = "Guardando...";

    try {
        const response = await fetch(getApiGuardarBiometriaUrl(), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                paciente_id: pacienteDoc,
                firma: b64,
                usuario: "Sistema"
            })
        });

        if (response.ok) {
            const data = await response.json();
            alert("✅ Firma guardada con éxito");
            btn.innerHTML = "✓ Guardada";
            btn.classList.replace('btn-success', 'btn-secondary');
            
            if (data.imagen_firma) {
                actualizarVistaFirmaPaciente(data.imagen_firma, "Firma Capturada");
                await refrescarFirmaPaciente(pacienteDoc, { silencioso: true, estado: "Firma Guardada" });

                // Cerrar modal automáticamente después de un pequeño delay
                setTimeout(() => {
                    const modal = document.getElementById('modal-biometria');
                    if (modal) modal.style.display = 'none';
                }, 1500);
            }
        } else {
            throw new Error("Error al guardar");
        }
    } catch (err) {
        alert("❌ Error al conectar con el servidor");
        btn.disabled = false;
        btn.innerHTML = originalText;
    }
}

/**
 * Polling mejorado para el modal y la vista principal
 */
function iniciarPollingHuellaModal(pacienteDoc) {
    // Huella deshabilitada en este desarrollo.
    // Se mantiene la función para compatibilidad con llamadas legacy.
    if (pacienteDoc) {
        refrescarFirmaPaciente(pacienteDoc, { silencioso: true, estado: "Firma actualizada" });
    }
}

/**
 * Lanza la captura de huella vía Deep Link
 */
function capturarHuella() {
    const pacienteDoc = document.getElementById("numero_documento").value;
    
    if (!pacienteDoc) {
        alert("Por favor, ingrese el número de documento del paciente.");
        return;
    }
    refrescarFirmaPaciente(pacienteDoc, { silencioso: false, estado: "Firma actualizada" });
}

/**
 * Redirige a la función de polling unificada
 */
function iniciarPollingHuella(pacienteDoc) {
    iniciarPollingHuellaModal(pacienteDoc);
}

/**
 * Inicializa los event listeners
 */
/**
 * Carga sugerencias de aseguradora en el datalist (el campo es texto libre,
 * ya que el nombre real de la aseguradora que trae el hospital no encaja en
 * una lista fija de opciones).
 */
async function cargarAseguradorasMeows() {
    try {
        const response = await fetch('/api/aseguradoras/', { credentials: 'same-origin' });
        if (!response.ok) return;
        const aseguradoras = await response.json();
        const datalist = document.getElementById('aseguradora-list');
        if (!datalist || !Array.isArray(aseguradoras)) return;
        datalist.innerHTML = aseguradoras.map(a => `<option value="${(a.nombre || '').replace(/"/g, '&quot;')}">`).join('');
    } catch (error) {
        console.error('Error al cargar aseguradoras:', error);
    }
}

async function inicializar() {
    // Cargar rangos desde el backend primero
    await cargarRangosDesdeBackend();

    // Sugerencias de aseguradora (no bloquea el resto de la inicialización)
    cargarAseguradorasMeows();

    // Si la medición viene de Dinámica, se deja el valor real editable como
    // número libre (igual que ya funciona "fr") en vez de forzarlo a encajar
    // en una de las opciones fijas del select — ver MEOWS_ORIGEN_DINAMICA en
    // formulario.html.
    if (!window.MEOWS_ORIGEN_DINAMICA) {
        // Convertir temperatura a select
        convertirTempASelect();

        // Convertir tensión arterial sistólica a select
        convertirTaSysASelect();

        // Convertir tensión arterial diastólica a select
        convertirTaDiaASelect();

        // Convertir frecuencia cardíaca a select
        convertirFcASelect();

        // Convertir frecuencia cardíaca fetal a select
        convertirFcfASelect();

        // Convertir saturación de oxígeno (SpO2) a select
        convertirSpo2ASelect();
    }

    // Sincronizar campos del paciente
    sincronizarCamposPaciente();

    // Selector práctico de hora (12h + AM/PM) del monitoreo
    inicializarSelectorHoraMonitoreo();

    const fechaMonitoreoInput = document.getElementById('fecha_monitoreo');
    if (fechaMonitoreoInput) {
        fechaMonitoreoInput.addEventListener('change', validarFechaHoraMonitoreo);
    }

    // Autocompletar datos del paciente (nombre, edad, aseguradora, cama, fecha ingreso)
    // desde el endpoint unificado al ingresar/perder foco el número de documento.
    const numeroDocumentoInput = document.getElementById('numero_documento');
    if (numeroDocumentoInput) {
        numeroDocumentoInput.addEventListener('blur', buscarPacienteUnificadoMeows);
        numeroDocumentoInput.addEventListener('keydown', function (e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                buscarPacienteUnificadoMeows();
            }
        });
        if (numeroDocumentoInput.value.trim()) buscarPacienteUnificadoMeows();
    }

    // Mostrar/actualizar usuario responsable en la card de firma
    const responsableInput = document.getElementById('responsable');
    if (responsableInput) {
        const nombreFirmaSpan = document.getElementById('nombre-firma-paciente');
        if (nombreFirmaSpan) {
            nombreFirmaSpan.textContent = responsableInput.value || '—';
        }
        responsableInput.addEventListener('input', function() {
            const nombreFirmaSpan = document.getElementById('nombre-firma-paciente');
            if (nombreFirmaSpan) {
                nombreFirmaSpan.textContent = this.value || '—';
            }
        });
    }

    async function procesarCambioParametro(input, usarApi = false) {
        const parametro = input.dataset.param;
        const valor = input.value;
        const score = usarApi
            ? await calcularScoreDesdeApi(parametro, valor)
            : calcularScore(parametro, valor);

        actualizarFeedback(parametro, valor, score);
        actualizarResumen();
    }

    // Event listener para cada input/select
    document.querySelectorAll('.parameter-input').forEach(input => {
        const esSelect = input.tagName === 'SELECT';

        if (esSelect) {
            // En selects usamos API al confirmar cambio
            input.addEventListener('change', function () {
                procesarCambioParametro(this, true);
            }, { passive: true, capture: false });
        } else {
            // Para inputs numéricos, mantener feedback inmediato local
            input.addEventListener('input', function () {
                procesarCambioParametro(this, false);
            }, { passive: true });

            // Al confirmar el cambio, recalcular contra API
            input.addEventListener('change', function () {
                procesarCambioParametro(this, true);
            }, { passive: true });
        }

        // Validar al perder foco
        input.addEventListener('blur', function () {
            const parametro = this.dataset.param;
            const valor = this.value;

            if (valor && valor !== '') {
                const score = calcularScore(parametro, valor);
                if (score === null) {
                    this.setCustomValidity('Valor fuera del rango esperado');
                } else {
                    this.setCustomValidity('');
                }
            }
        });
    });

    // Modo edición: los inputs ya vienen con "value" prellenado desde el
    // servidor (formulario.html los rellena con los valores de la medición
    // que se está corrigiendo), pero eso no dispara 'change' por sí solo, así
    // que aquí se fuerza el recálculo de puntaje/resumen para cada uno.
    document.querySelectorAll('.parameter-input').forEach(input => {
        if (input.value !== '') {
            input.dispatchEvent(new Event('change'));
        }
    });

    // Botón limpiar
    const btnLimpiar = document.getElementById('btn-limpiar');
    if (btnLimpiar) {
        btnLimpiar.addEventListener('click', function () {
            if (confirm('¿Está seguro de limpiar todos los campos?')) {
                document.querySelectorAll('.parameter-input').forEach(input => {
                    input.value = '';
                    const parametro = input.dataset.param;
                    actualizarFeedback(parametro, '', null);
                });
                actualizarResumen();
            }
        });
    }

    // Validación del formulario antes de enviar
    const form = document.getElementById('meows-form');
    if (form) {
        form.addEventListener('submit', function (e) {
            // No todos los parámetros se diligencian siempre (ej: FCF o Glasgow pueden no aplicar).
            // Solo se bloquea el guardado si un campo SÍ diligenciado tiene un valor fuera de rango.
            let isValid = true;
            const inputs = document.querySelectorAll('.parameter-input');

            inputs.forEach(input => {
                input.classList.remove('error');
                if (input.value && input.value !== '') {
                    const score = calcularScore(input.dataset.param, input.value);
                    if (score === null) {
                        isValid = false;
                        input.classList.add('error');
                    }
                }
            });

            if (!validarFechaHoraMonitoreo()) {
                isValid = false;
            }

            if (!isValid) {
                e.preventDefault();
                alert('Por favor revise los valores ingresados: hay parámetros fuera de rango o falta la fecha/hora del monitoreo.');
                return false;
            }
        });
    }

    // Calcular resumen inicial
    actualizarResumen();

    // Botón generar PDF
    const btnGenerarPDF = document.getElementById('btn-generar-pdf');
    if (btnGenerarPDF) {
        btnGenerarPDF.addEventListener('click', async function () {
            const textoOriginal = btnGenerarPDF.innerHTML;
            btnGenerarPDF.disabled = true;
            btnGenerarPDF.innerHTML = '<span class="btn-icon">⏳</span>Generando PDF...';

            try {
                // Ir directo al PDF si ya tenemos el id en la vista (evita una consulta extra)
                const pacienteIdActual = obtenerPacienteIdActual();
                if (pacienteIdActual) {
                    const pdfTemplate = getMeowsUrl('pdfTemplate', '/pdf/0/');
                    window.location.href = buildUrlFromTemplate(pdfTemplate, pacienteIdActual);
                    return;
                }

                // Fallback: buscar por documento solo si no hay id disponible
                const numeroDocInput = document.getElementById('numero_documento');
                const numeroDoc = numeroDocInput ? numeroDocInput.value.trim() : '';

                if (!numeroDoc) {
                    alert('Por favor, ingrese el número de documento del paciente para generar el PDF.');
                    return;
                }

                const apiBuscar = getMeowsUrl('apiBuscarPaciente', '/api/buscar-paciente/');
                const response = await fetch(`${apiBuscar}?documento=${encodeURIComponent(numeroDoc)}`);
                const data = await response.json();

                if (data.success && data.paciente && data.paciente.id) {
                    const pdfTemplate = getMeowsUrl('pdfTemplate', '/pdf/0/');
                    window.location.href = buildUrlFromTemplate(pdfTemplate, data.paciente.id);
                } else {
                    alert('No se encontró el paciente. Por favor, guarde primero una medición para este paciente antes de generar el PDF.');
                }
            } catch (error) {
                console.error('Error al buscar paciente para PDF:', error);
                alert('Error al generar el PDF. Por favor, intente nuevamente.');
            } finally {
                // Si no hubo navegación, restaurar botón
                btnGenerarPDF.disabled = false;
                btnGenerarPDF.innerHTML = textoOriginal;
            }
        });
    }

    // Botón capturar huella (ahora abre modal)
    const btnCapturarHuella = document.getElementById('btn-capturar-huella');
    if (btnCapturarHuella) {
        btnCapturarHuella.removeEventListener('click', capturarHuella); // Limpiar anterior
        btnCapturarHuella.addEventListener('click', abrirModalBiometria);
    }

    const btnRefrescarFirma = document.getElementById('btn-refrescar-firma');
    if (btnRefrescarFirma) {
        btnRefrescarFirma.addEventListener('click', async () => {
            const doc = (document.getElementById("numero_documento")?.value || '').trim();
            if (!doc) {
                alert("Ingrese el documento del paciente para refrescar la firma.");
                return;
            }
            await refrescarFirmaPaciente(doc, { silencioso: false, estado: "Firma actualizada" });
        });
    }

    // Eventos del Modal
    const btnCerrarModal = document.getElementById('btn-cerrar-modal-biometria');
    if (btnCerrarModal) {
        btnCerrarModal.addEventListener('click', () => {
            document.getElementById('modal-biometria').style.display = 'none';
        });
    }

    const btnFinalizar = document.getElementById('btn-finalizar-biometria');
    if (btnFinalizar) {
        btnFinalizar.addEventListener('click', () => {
            document.getElementById('modal-biometria').style.display = 'none';
        });
    }

    const btnGuardarFirma = document.getElementById('btn-guardar-firma');
    if (btnGuardarFirma) {
        btnGuardarFirma.addEventListener('click', guardarFirmaDigital);
    }

    const btnLimpiarFirma = document.getElementById('btn-limpiar-firma');
    if (btnLimpiarFirma) {
        btnLimpiarFirma.addEventListener('click', () => {
            if (firmaPad) firmaPad.limpiar();
            const btnG = document.getElementById('btn-guardar-firma');
            btnG.disabled = false;
            btnG.innerHTML = "Guardar Firma";
            btnG.classList.replace('btn-secondary', 'btn-success');
        });
    }

    const btnTriggerHuellaModal = document.getElementById('btn-trigger-huella-modal');
    if (btnTriggerHuellaModal) {
        btnTriggerHuellaModal.addEventListener('click', capturarHuella);
    }

    // Si la vista abre con un paciente ya cargado, mostrar su firma guardada.
    const docInicial = (document.getElementById("numero_documento")?.value || '').trim();
    if (docInicial) {
        refrescarFirmaPaciente(docInicial, { silencioso: true, estado: "Firma Histórica" });
    }
}

// Inicializar cuando el DOM esté listo
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', inicializar);
} else {
    inicializar();
}

