"""
2026-10-19: UN registro de Control Posparto (FRSPA-007) por paciente e ingreso.

HALLAZGO (producción): pacientes 1007012196 (ingreso 1832634) y 1078180366
(ingreso 1833170) con DOS registros en el mismo ingreso. El formulario,
cuando no lograba cargar el registro ya guardado (red lenta, sesión, error
del servidor), quedaba en blanco y el autoguardado creaba uno NUEVO; desde
ahí la pantalla abría el más reciente (vacío) y los controles ya guardados
"desaparecían" (seguían en el otro registro).

Ahora:
- crear un registro cuando ya existe uno de ese ingreso NO crea otro: lo
  que trae la pantalla se agrega al existente sin pisar nada
  (fusionar_en_registro) y se responde con ese registro;
- entre varios registros de un mismo ingreso (los duplicados que ya
  existen) se abre siempre el principal (registro_principal), no el más
  reciente;
- fusionar_registros() junta un duplicado en el principal (comando
  fusionar_registros_posparto).
"""
import logging
from contextlib import contextmanager

from django.db import transaction

from .models import (
    ControlFetocardia, ControlGlobo, ControlPostpartoInmediato, ControlRecienNacido,
    ControlSangrado, ControlSutura, GlucometriaRecienNacido, RegistroParto,
    recalcular_estados_sangrado,
)

logger = logging.getLogger(__name__)

# Cronograma de la vigilancia (mismo PP_MINUTOS de formulario.html).
MINUTOS_CRONOGRAMA = (15, 30, 45, 60, 75, 90, 105, 120, 150, 180, 240, 300, 360)

# Controles por minuto: (relación en RegistroParto, modelo, nombre, campos que lo identifican).
CONTROLES_POR_MINUTO = (
    ('controles_sangrado', ControlSangrado, 'Sangrado', ('hora', 'cc')),
    ('controles_globo', ControlGlobo, 'Globo de seguridad', ('hora', 'estado')),
    ('controles_sutura', ControlSutura, 'Sutura y heridas', ('hora', 'estado')),
)

# Campos del registro que nunca se copian de uno a otro.
_CAMPOS_NO_FUSIONAR = {
    'id', 'atencion', 'created_at', 'updated_at', 'completado_en', 'completado_por',
    'creado_por', 'nombre_firma_paciente', 'duenos_campos',  # 2026-10-19: los dueños se pasan aparte
}


def _vacio(valor):
    return valor is None or valor == ''


def cantidad_datos(registro):
    """Cuántos datos clínicos tiene (para elegir el registro principal)."""
    total = (registro.controles_sangrado.count() + registro.controles_globo.count()
             + registro.controles_sutura.count() + registro.controles_fetocardia.count()
             + registro.controles_postparto.count())
    for rn in registro.recien_nacidos.all():
        total += 1 + (1 if rn.huella_pdf else 0)
    return total


def registro_principal(registros):
    """Entre varios registros del mismo ingreso: el cerrado; si no, el que
    más datos tiene; a igualdad, el más antiguo. None si no hay ninguno."""
    registros = list(registros)
    if not registros:
        return None
    return sorted(registros, key=lambda r: (
        r.completado_en is None, -cantidad_datos(r), r.created_at,
    ))[0]


def registros_del_mismo_ingreso(identificacion, atencion=None, ingreso=''):
    """Registros ya guardados de esta paciente en el ingreso al que iría uno
    nuevo. Primero con el selector de ingresos (Dinámica, igual que
    por-atencion); sin Dinámica, por el ingreso o la atención del enlace."""
    identificacion = (identificacion or '').strip()
    if not identificacion:
        return RegistroParto.objects.none()
    try:
        from obstetriciaunificador.ingresos import CLAVE_SIN_INGRESO, resumen_ingresos
        resumen, grupos = resumen_ingresos(identificacion, 'control_posparto', ingreso or '', fresco=True)
    except Exception:
        logger.warning('Unicidad posparto: sin selector de ingresos para %s', identificacion, exc_info=True)
        resumen, grupos = None, {}
    if resumen and resumen.get('elegido') and resumen['elegido'] != CLAVE_SIN_INGRESO \
            and not str(resumen['elegido']).startswith('triaje'):
        return RegistroParto.objects.filter(id__in=grupos.get(resumen['elegido'], []))
    numero = (getattr(atencion, 'numero_ingreso', '') or '').strip()
    if numero:
        return RegistroParto.objects.filter(identificacion=identificacion, atencion__numero_ingreso=numero)
    if atencion is not None:
        return RegistroParto.objects.filter(identificacion=identificacion, atencion=atencion)
    return RegistroParto.objects.none()


@contextmanager
def bloqueo_creacion(identificacion):
    """Dos guardados que crean a la vez el registro de la misma paciente
    (autoguardado + huella, dos tablets) se atienden uno detrás del otro."""
    from obstetriciaunificador.repositorio import bloqueo_envio
    with bloqueo_envio(f'crear_registro_posparto|{(identificacion or "").strip()}', espera_segundos=30):
        yield


def _minuto_libre(ocupados):
    return next((m for m in MINUTOS_CRONOGRAMA if m not in ocupados), None)


def _agregar_control_minuto(registro, modelo, nombre, campos_id, datos, firma, avisos):
    """Agrega un control de vigilancia al registro. Si su minuto ya está
    ocupado por el mismo control (reintento) no hace nada; si lo ocupa otro
    distinto, pasa al siguiente minuto libre (mismo criterio que la pantalla)."""
    minuto = datos.get('minuto_control')
    existente = modelo.objects.filter(registro=registro, minuto_control=minuto).first()
    if existente is not None:
        if all(str(getattr(existente, c)) == str(datos.get(c)) for c in campos_id if c in datos):
            return False
        ocupados = set(modelo.objects.filter(registro=registro).values_list('minuto_control', flat=True))
        libre = _minuto_libre(ocupados)
        if libre is None:
            avisos.append(f'{nombre}: el control de {minuto} min no se agregó (los 13 controles ya estaban registrados).')
            return False
        avisos.append(f'{nombre}: el control de {minuto} min ya estaba registrado; este quedó como el de {libre} min.')
        datos = {**datos, 'minuto_control': libre}
    modelo.objects.create(registro=registro, **datos, **firma)
    return True


def fusionar_en_registro(registro, datos, firma, firma_responsable):
    """Agrega al `registro` existente lo que traía un guardado que iba a crear
    otro (validated_data de RegistroPartoSerializer). Nunca pisa un dato ya
    guardado: solo llena lo vacío y agrega controles que no estén. Devuelve
    los avisos para la pantalla."""
    avisos = []
    datos = dict(datos)
    fetocardia = datos.pop('controles_fetocardia', None) or []
    rn_a = datos.pop('control_recien_nacido', None)
    rn_b = datos.pop('control_recien_nacido_b', None)
    postparto = datos.pop('controles_postparto', None) or []
    vigilancia = {rel: datos.pop(rel, None) or [] for rel, *_ in CONTROLES_POR_MINUTO}

    if registro.completado_en is not None:
        return ['El registro de esta paciente ya estaba cerrado: no se le agregaron datos.']

    with transaction.atomic():
        cambiados = []
        for campo, valor in datos.items():
            if campo in _CAMPOS_NO_FUSIONAR or _vacio(valor):
                continue
            if campo == 'numero_fetos':
                if (valor or 1) > (registro.numero_fetos or 1):
                    registro.numero_fetos = valor
                    cambiados.append(campo)
                continue
            if _vacio(getattr(registro, campo, None)):
                setattr(registro, campo, valor)
                cambiados.append(campo)
        if cambiados:
            registro.save(update_fields=cambiados)
        # 2026-10-19: quien llenó lo que estaba vacío queda como su dueño.
        from .propiedad import CAMPOS_REGISTRO_CON_DUENO, asignar_duenos, campos_rn_con_dueno
        usuario, nombre = firma.get('registrado_usuario', ''), firma.get('registrado_por', '')
        asignar_duenos(registro, cambiados, {}, CAMPOS_REGISTRO_CON_DUENO, usuario, nombre)
        firma_g = {'registrado_por': nombre, 'registrado_usuario': usuario}

        for fc in fetocardia:
            fc = dict(fc)
            if fc.get('fecha') is None or fc.get('hora') is None or fc.get('fetocardia') is None:
                continue
            feto = fc.get('feto') or 1
            feto = feto if 1 <= feto <= (registro.numero_fetos or 1) else 1
            if not registro.controles_fetocardia.filter(fecha=fc['fecha'], hora=fc['hora'], feto=feto).exists():
                ControlFetocardia.objects.create(
                    registro=registro, fecha=fc['fecha'], hora=fc['hora'], fetocardia=fc['fetocardia'],
                    feto=feto, **firma_responsable)

        for feto, rn_datos in ((1, rn_a), (2, rn_b)):
            if not rn_datos or feto > (registro.numero_fetos or 1):
                continue
            rn_datos = dict(rn_datos)
            glucometrias = list(rn_datos.pop('glucometrias', None) or []) + list(rn_datos.pop('glucometrias_agregar', None) or [])
            rn_datos.pop('glucometrias_quitar', None)
            rn = registro.recien_nacidos.filter(feto=feto).first()
            if rn is None:
                rn = ControlRecienNacido.objects.create(registro=registro, feto=feto, **rn_datos, **firma)
                llenar = list(rn_datos)
            else:
                llenar = [c for c, v in rn_datos.items() if not _vacio(v) and _vacio(getattr(rn, c, None))]
                for c in llenar:
                    setattr(rn, c, rn_datos[c])
                if llenar:
                    rn.save(update_fields=llenar)
            asignar_duenos(rn, llenar, {}, campos_rn_con_dueno(), usuario, nombre)
            for g in glucometrias:
                if not rn.glucometrias.filter(hora=g['hora'], resultado=g['resultado']).exists():
                    GlucometriaRecienNacido.objects.create(control_rn=rn, hora=g['hora'], resultado=g['resultado'],
                                                           **firma_g)

        for cp in postparto:
            cp = {k: v for k, v in dict(cp).items() if k != 'responsable'}
            if not registro.controles_postparto.filter(minuto_control=cp.get('minuto_control')).exists():
                ControlPostpartoInmediato.objects.create(registro=registro, **cp, **firma_responsable)

        hubo_sangrado = False
        for rel, modelo, nombre, campos_id in CONTROLES_POR_MINUTO:
            # Primero los que tienen su minuto libre; después los que chocan
            # (si no, uno reubicado le quitaba el minuto a otro que sí era suyo).
            ocupados = set(modelo.objects.filter(registro=registro).values_list('minuto_control', flat=True))
            controles = sorted(vigilancia[rel], key=lambda c: c.get('minuto_control') in ocupados)
            for control in controles:
                agregado = _agregar_control_minuto(registro, modelo, nombre, campos_id, dict(control), firma, avisos)
                hubo_sangrado = hubo_sangrado or (agregado and modelo is ControlSangrado)
        if hubo_sangrado:
            recalcular_estados_sangrado(registro)
        registro.sincronizar_horas_nacimiento()
    return avisos


def fusionar_registros(destino, origen):
    """Pasa al `destino` todo lo del duplicado `origen` (comando
    fusionar_registros_posparto). Los controles conservan su firma original
    (se mueven, no se copian). Lo que choca con un dato del destino se deja
    en el origen y se informa. Devuelve (movidos, conflictos)."""
    movidos, conflictos = [], []
    with transaction.atomic():
        cambiados = []
        for campo in [f.name for f in RegistroParto._meta.concrete_fields]:
            if campo in _CAMPOS_NO_FUSIONAR:
                continue
            valor = getattr(origen, campo)
            if _vacio(valor):
                continue
            if campo == 'numero_fetos':
                if (valor or 1) > (destino.numero_fetos or 1):
                    destino.numero_fetos = valor
                    cambiados.append(campo)
                continue
            actual = getattr(destino, campo)
            if _vacio(actual):
                setattr(destino, campo, valor)
                cambiados.append(campo)
            elif actual != valor and not isinstance(valor, bool) and campo != 'gestas':
                conflictos.append(f'Campo {campo}: se conserva "{actual}" (el duplicado tenía "{valor}").')
        if cambiados:
            # 2026-10-19: cada dato conserva a su dueño original.
            destino.duenos_campos = {**(destino.duenos_campos or {}),
                                     **{c: d for c, d in (origen.duenos_campos or {}).items() if c in cambiados}}
            destino.save(update_fields=cambiados + ['duenos_campos'])
            movidos.append(f'Datos del registro: {", ".join(cambiados)}')

        for rel, modelo, nombre, _ in CONTROLES_POR_MINUTO + (
                ('controles_postparto', ControlPostpartoInmediato, 'Control postparto', ()),):
            ocupados = set(getattr(destino, rel).values_list('minuto_control', flat=True))
            for control in getattr(origen, rel).all():
                if control.minuto_control in ocupados:
                    conflictos.append(f'{nombre} {control.minuto_control} min: ya existe en el registro principal.')
                    continue
                control.registro = destino
                control.save(update_fields=['registro'])
                ocupados.add(control.minuto_control)
                movidos.append(f'{nombre} {control.minuto_control} min')
        recalcular_estados_sangrado(destino)

        for fc in origen.controles_fetocardia.all():
            if destino.controles_fetocardia.filter(fecha=fc.fecha, hora=fc.hora, feto=fc.feto).exists():
                conflictos.append(f'Fetocardia {fc.fecha} {fc.hora}: ya existe en el registro principal.')
                continue
            fc.registro = destino
            fc.save(update_fields=['registro'])
            movidos.append(f'Fetocardia {fc.fecha} {fc.hora}')

        for rn in origen.recien_nacidos.all():
            rn_destino = destino.recien_nacidos.filter(feto=rn.feto).first()
            if rn_destino is None:
                rn.registro = destino
                rn.save(update_fields=['registro'])
                movidos.append(f'Recién nacido (feto {rn.feto})' + (' con huella' if rn.huella_pdf else ''))
                continue
            llenar = [f.name for f in ControlRecienNacido._meta.concrete_fields
                      if f.name not in ('id', 'registro', 'feto', 'duenos_campos')
                      and not _vacio(getattr(rn, f.name)) and _vacio(getattr(rn_destino, f.name))]
            if not rn_destino.huella_pdf and rn.huella_pdf:
                llenar += [c for c in ('huella_pdf', 'huella_subida_por', 'huella_subida_en') if c not in llenar]
            for c in llenar:
                setattr(rn_destino, c, getattr(rn, c))
            if 'huella_pdf' in llenar and 'huella_subida_usuario' not in llenar:
                rn_destino.huella_subida_usuario = rn.huella_subida_usuario
                llenar.append('huella_subida_usuario')
            if llenar:
                rn_destino.duenos_campos = {**(rn_destino.duenos_campos or {}),
                                            **{c: d for c, d in (rn.duenos_campos or {}).items() if c in llenar}}
                rn_destino.save(update_fields=llenar + ['duenos_campos'])
                movidos.append(f'Recién nacido (feto {rn.feto}): {", ".join(llenar)}')
                if 'huella_pdf' in llenar:
                    # La huella ya es del destino: que el origen no la borre.
                    type(rn).objects.filter(pk=rn.pk).update(huella_pdf=None)
            for g in rn.glucometrias.all():
                if not rn_destino.glucometrias.filter(hora=g.hora, resultado=g.resultado).exists():
                    g.control_rn = rn_destino
                    g.save(update_fields=['control_rn'])
                    movidos.append(f'Glucometría {g.hora}')

        # Quiénes participaron y la bitácora pasan también al principal.
        for p in origen.participaciones.all():
            existente = destino.participaciones.filter(profesional=p.profesional).first()
            if existente is None:
                p.registro = destino
                p.save(update_fields=['registro'])
            else:
                existente.primera_vez = min(existente.primera_vez, p.primera_vez)
                existente.ultima_vez = max(existente.ultima_vez, p.ultima_vez)
                existente.save(update_fields=['primera_vez', 'ultima_vez'])
        origen.cambios.update(registro=destino)
        destino.sincronizar_horas_nacimiento()
    return movidos, conflictos


def registro_vacio(registro):
    """True si el registro ya no tiene ningún dato clínico propio."""
    return cantidad_datos(registro) == 0 and not registro.recien_nacidos.exists()
