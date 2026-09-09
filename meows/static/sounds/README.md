# Sonidos de Alerta MEOWS

Esta carpeta contiene los archivos de audio para las alertas sonoras del sistema MEOWS.

## Archivo actual (un solo tono — desde 2026-09-09):

- **alert_urgente.wav**: dos pitidos cortos y agudos (C6/E6, ~0.78s en total),
  generado programáticamente (sin dependencias externas, solo el módulo `wave`
  de Python) el 2026-09-08. Es el único tono del sistema: suena para **AMARILLO
  y ROJO** (las dos únicas alertas que quedan, a pedido de enfermería —
  Blanco/Verde dejaron de notificar del todo, ver `meows/management/commands/
  sincronizar_signos_vitales_dinamica.py:disparar_alerta`).

- **alert_soft.wav**: ya NO se usa. Existía un segundo tono más suave para
  Blanco/Verde/Amarillo (2026-09-04 a 2026-09-08), pero se quitó al dejar de
  notificarse Blanco/Verde y unificarse el sonido de Amarillo con el de Rojo.
  Se deja el archivo en la carpeta por si se quiere reutilizar en el futuro,
  pero ningún `<audio>` de `obstetricia/sidebar.html` lo referencia ya.

Reemplaza `alert_urgente.wav` por un archivo real grabado/elegido a mano
cuando haya uno disponible; el `<audio id="alertSoundRojo">` en
`obstetricia/sidebar.html` acepta cualquier `.wav`/`.mp3` puesto en esta ruta
con el mismo nombre (o cambia el `src` si usas otro nombre).

## Características recomendadas si se reemplaza:

- Corto pero agudo/llamativo — debe distinguirse claramente como alerta
  urgente, sin llegar a ser insoportable con tomas frecuentes.
- Duración recomendada: 0.6 – 1.2 segundos.

## Nota:

El sistema reproduce este tono para **toda** medición nueva de riesgo AMARILLO
o ROJO (nunca Blanco/Verde) importada de Dinámica, con un pequeño escalonado
entre alertas si llegan varias juntas (ver `sonarAlertaMeows()` y
`RETRASO_ENTRE_SONIDOS_MS` en `obstetricia/sidebar.html`). Si el archivo
llegara a faltar o el navegador bloquea la reproducción, cae automáticamente
a un beep sintetizado de respaldo (`pitidoRespaldoUrgente()`) — el sistema
nunca se rompe por esto, en el peor caso suena el respaldo en vez del tono real.
