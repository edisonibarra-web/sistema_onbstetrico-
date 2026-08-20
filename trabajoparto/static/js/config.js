/**
 * Configuración de la aplicación - Sistema Clínico Hospitalario
 * 
 * Este archivo centraliza la configuración de la aplicación, permitiendo
 * cambiar fácilmente entre entornos (desarrollo, pruebas, producción) sin
 * modificar el código fuente.
 * 
 * La URL base del backend puede configurarse de las siguientes formas:
 * 1. Variable de entorno del navegador (si está disponible)
 * 2. Variable global window.API_BASE_URL (definida antes de cargar este script)
 * 3. Archivo .env (requiere procesamiento en build time)
 * 4. Valor por defecto según el entorno detectado
 */

(function () {
    'use strict';

    /**
     * Detección automática del entorno
     */
    function detectarEntorno() {
        const hostname = window.location.hostname;
        const protocol = window.location.protocol;

        // Desarrollo local
        if (hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '') {
            return 'development';
        }

        // Producción (puedes ajustar estos dominios según tu caso)
        if (hostname.includes('produccion') || hostname.includes('prod')) {
            return 'production';
        }

        // Pruebas/Staging
        if (hostname.includes('staging') || hostname.includes('test') || hostname.includes('qa')) {
            return 'staging';
        }

        // Por defecto, asumir desarrollo
        return 'development';
    }

    /**
     * Inferir URL del backend usando host y puerto actuales (evita depender de IP
     * o puerto fijos). El backend se sirve desde el mismo proceso Django que el
     * frontend, así que el puerto correcto es siempre el de la página actual.
     * Ejemplo: frontend en http://172.20.x.x:8001 -> backend http://172.20.x.x:8001/api
     */
    function inferirURLBackendPorHostActual() {
        const host = (window.location.hostname && window.location.hostname !== '0.0.0.0')
            ? window.location.hostname
            : 'localhost';
        const protocolo = window.location.protocol === 'https:' ? 'https:' : 'http:';
        const puerto = window.location.port ? `:${window.location.port}` : '';
        return `${protocolo}//${host}${puerto}/api`;
    }

    /**
     * Obtener la URL base del backend según el entorno
     */
    function obtenerURLBaseBackend() {
        const entorno = detectarEntorno();

        // Prioridad 1: Variable global definida manualmente (útil para testing)
        if (typeof window !== 'undefined' && window.API_BASE_URL) {
            console.log('🔧 Usando API_BASE_URL desde window.API_BASE_URL:', window.API_BASE_URL);
            return window.API_BASE_URL;
        }

        // Prioridad 2: Variable de entorno del navegador (si está disponible)
        // Nota: Las variables de entorno del navegador requieren procesamiento en build time
        // Para proyectos simples, puedes usar meta tags en el HTML

        // Prioridad 3: Obtener desde meta tag (si está definido en el HTML)
        const metaApiUrl = document.querySelector('meta[name="api-base-url"]');
        if (metaApiUrl && metaApiUrl.content) {
            console.log('🔧 Usando API_BASE_URL desde meta tag:', metaApiUrl.content);
            return metaApiUrl.content;
        }

        // Prioridad 4: Valores por defecto según entorno
        // Base SOLO hasta /api (sin rutas). Ej.: fetch(`${API_BASE}/pacientes/listar-embarazadas/?...`)
        // Si cambia la IP del servidor, usar el host actual mantiene la conectividad.
        const inferida = inferirURLBackendPorHostActual();
        const configuracionesPorEntorno = {
            development: inferida,
            staging: 'http://staging-api.ejemplo.com/api',
            production: 'https://api.ejemplo.com/api'
        };

        const urlBase = configuracionesPorEntorno[entorno] || configuracionesPorEntorno.development;
        console.log(`🔧 Entorno detectado: ${entorno}, usando URL base: ${urlBase}`);

        return urlBase;
    }

    /**
     * Validar que la URL base sea válida
     */
    function validarURLBase(url) {
        try {
            const urlObj = new URL(url);
            // Verificar que sea HTTP o HTTPS
            if (!['http:', 'https:'].includes(urlObj.protocol)) {
                console.warn('⚠️ La URL base debe usar HTTP o HTTPS');
                return false;
            }
            return true;
        } catch (e) {
            console.error('❌ URL base inválida:', url, e);
            return false;
        }
    }

    /**
     * Configuración de la aplicación
     */
    const Config = {
        // URL base del backend API
        API_BASE_URL: (function () {
            const url = obtenerURLBaseBackend();
            if (!validarURLBase(url)) {
                console.error('❌ URL base inválida, usando valor por defecto');
                return inferirURLBackendPorHostActual();
            }
            return url;
        })(),

        // Ruta del template HTML usado para armar la vista previa de impresión en frontend
        PDF_TEMPLATE_PATH: '/templates/clinico/impresion_formulario.html',

        // Entorno actual
        ENVIRONMENT: detectarEntorno(),

        // Configuración de timeouts (en milisegundos)
        REQUEST_TIMEOUT: 30000, // 30 segundos

        // Configuración de reintentos
        MAX_RETRIES: 3,
        RETRY_DELAY: 1000, // 1 segundo

        // Configuración de caché
        CACHE_ENABLED: false,
        CACHE_TIMEOUT: 0,

        // Configuración de logging
        LOG_LEVEL: detectarEntorno() === 'production' ? 'error' : 'debug',

        /**
         * Obtener la URL completa para un endpoint
         * @param {string} endpoint - Endpoint relativo (ej: '/pacientes/')
         * @returns {string} URL completa
         */
        getFullURL: function (endpoint) {
            // Asegurar que el endpoint comience con /
            const endpointNormalizado = endpoint.startsWith('/') ? endpoint : '/' + endpoint;
            // Eliminar / al final de API_BASE_URL si existe
            const baseUrl = this.API_BASE_URL.endsWith('/')
                ? this.API_BASE_URL.slice(0, -1)
                : this.API_BASE_URL;
            return baseUrl + endpointNormalizado;
        },

        /**
         * Verificar si estamos en desarrollo
         */
        isDevelopment: function () {
            return this.ENVIRONMENT === 'development';
        },

        /**
         * Verificar si estamos en producción
         */
        isProduction: function () {
            return this.ENVIRONMENT === 'production';
        },

        /**
         * Obtener información de configuración (útil para debugging)
         */
        getInfo: function () {
            return {
                environment: this.ENVIRONMENT,
                apiBaseUrl: this.API_BASE_URL,
                requestTimeout: this.REQUEST_TIMEOUT,
                maxRetries: this.MAX_RETRIES,
                cacheEnabled: this.CACHE_ENABLED,
                logLevel: this.LOG_LEVEL
            };
        }
    };

    // Exponer configuración globalmente
    if (typeof window !== 'undefined') {
        window.AppConfig = Config;
    }

    // Log de configuración en desarrollo
    if (Config.isDevelopment()) {
        console.log('📋 Configuración de la aplicación:', Config.getInfo());
    }

    // Exportar para módulos (si se usa un bundler)
    if (typeof module !== 'undefined' && module.exports) {
        module.exports = Config;
    }
})();
