# Sonidos de Alerta MEOWS

Esta carpeta contiene los archivos de audio para las alertas sonoras del sistema MEOWS.

## Archivos actuales (dos tonos, según urgencia — desde 2026-09-08):

- **alert_soft.wav**: tono suave de dos notas (~0.8s, D5 → G5, con fade in/out),
  generado programáticamente (sin dependencias externas, solo el módulo `wave`
  de Python) el 2026-09-04. Se usa para riesgo **Blanco/Verde/Amarillo** — este
  siempre fue su propósito original ("no debe ser estridente" abajo); quedó
  libre para esto al crearse `alert_urgente.wav` específico para Rojo.
- **alert_urgente.wav**: dos pitidos cortos y agudos (C6/E6, ~0.78s en total),
  generado igual de forma programática el 2026-09-08. Se usa **exclusivamente
  para riesgo ROJO** — a propósito más llamativo y con un ritmo distinto al
  tono suave, para que se distinga de oído cuál llegó sin tener que mirar la
  pantalla.

Reemplaza cualquiera de los dos por un archivo real grabado/elegido a mano
cuando haya uno disponible; los `<audio>` en `obstetricia/sidebar.html`
(`#alertSoundRojo`, `#alertSoundSuave`) aceptan cualquier `.wav`/`.mp3` puesto
en esta ruta con el mismo nombre (o cambia el `src` si usas otro nombre).

## Características recomendadas si se reemplazan:

- **alert_soft.wav** (Blanco/Verde/Amarillo): corto, grave, suave — no debe
  sonar a alarma ni saturar al personal con tomas frecuentes.
- **alert_urgente.wav** (Rojo): corto pero agudo/llamativo — sí debe
  distinguirse claramente como el más urgente de los dos.
- Duración recomendada para ambos: 0.6 – 1.2 segundos.

## Nota:

El sistema reproduce alguno de los dos tonos para **toda** medición nueva
(Blanco a Rojo, no solo riesgo alto — decisión del usuario, 2026-09-03)
importada de Dinámica o registrada manualmente; cuál de los dos suena depende
del riesgo de esa medición (ver `sonarAlertaRoja()`/`sonarAlertaSuave()` en
`obstetricia/sidebar.html`). Si el archivo correspondiente llegara a faltar o
el navegador bloquea la reproducción, cada uno cae automáticamente a su
propio beep sintetizado de respaldo (`pitidoRespaldoUrgente()` /
`pitidoRespaldoSuave()`) — el sistema nunca se rompe por esto, en el peor
caso suena el respaldo en vez del tono real.
