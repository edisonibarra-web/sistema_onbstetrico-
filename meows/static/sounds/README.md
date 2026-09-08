# Sonidos de Alerta MEOWS

Esta carpeta contiene los archivos de audio para las alertas sonoras del sistema MEOWS.

## Archivo actual:

- **alert_soft.wav**: tono suave de dos notas (~0.8s, D5 → G5, con fade in/out)
  generado programáticamente (sin dependencias externas, solo el módulo `wave`
  de Python) el 2026-09-04 — ver `sistema_obstetrico/scripts` o el historial de
  esta conversación si hay que regenerarlo. Reemplázalo por un archivo real
  grabado/elegido a mano cuando haya uno disponible; el `<audio>` en
  `obstetricia/sidebar.html` acepta cualquier `.wav` o `.mp3` que se le ponga
  en esta ruta con ese mismo nombre (o cambia el `src` si usas otro nombre).

## Características del sonido recomendado (si se reemplaza):

- ✅ Tipo: tono corto, grave, suave
- ✅ Duración: 0.8 – 1.2 segundos
- ✅ No debe ser estridente
- ✅ No debe saturar al personal

## Nota:

El sistema reproduce este sonido para **toda** medición nueva (Blanco a Rojo,
no solo riesgo alto — decisión del usuario, 2026-09-03) importada de Dinámica
o registrada manualmente. Si el archivo llegara a faltar o el navegador
bloquea la reproducción, cae automáticamente a un beep sintetizado de
respaldo (ver `pitidoRespaldo()` en `obstetricia/sidebar.html`) — el sistema
nunca se rompe por esto, en el peor caso suena el respaldo en vez del tono.
