"""
Sincroniza automáticamente el parámetro "Frecuencia Cardiaca Fetal" (card
FETAL de Trabajo de Parto) desde Dinámica — mismo dato que ya usa MEOWS
(FETOCARDIO, OID 20 de HCNTIPSVIT), para no obligar a la enfermera a
digitarlo dos veces en dos módulos distintos.

2026-09-09: primera versión, alcance acotado a pedido — SOLO este parámetro
puntual (Parametro id=8, "FREC_CARD_FETAL"), NO todo el módulo de Trabajo de
Parto. Los demás parámetros de la card FETAL (Movimientos Fetales,
Presentación) siguen siendo 100% manuales.

2026-09-11: se quita el requisito de que la paciente ya tuviera un
Formulario (hoja) guardado a mano. A pedido explícito, esto debe funcionar
"por primera vez" igual que MEOWS (que no depende de una hoja previa): si
la paciente activa en Sala de Partos no tiene aún Paciente/Formulario en
Trabajo de Parto, este comando los crea con datos mínimos (mismos defaults
que ya usa el frontend en guardarFormulario: codigo FRSPA-022, version 1,
estado 'g' = Gestante) para poder adjuntar la lectura. El `responsable`
queda explícitamente marcado como sincronización automática — NO se
inventa el nombre de ningún profesional — y la enfermera lo sobrescribe
con su nombre real la primera vez que guarda algo a mano en esa hoja
(mismo formulario_id, vía PUT).

Por qué se crea una "hora de registro" nueva en vez de solo devolver el dato:
a diferencia de MEOWS (una Medicion = una toma completa con su propia hora),
Trabajo de Parto organiza sus datos en una grilla por horario: el frontend
solo muestra el valor de un parámetro para la hora exacta que la enfermera
tenga seleccionada/creada en ese momento (ver sincronizarMedicionesGuardadas
en trabajoparto/static/js/main.js). Que Dinámica "traiga sola" el dato
implica entonces crear la columna de hora correspondiente, igual que MEOWS
crea una Medicion nueva por cada lectura de Dinámica — la enfermera la ve
igual que si alguien ya la hubiera diligenciado, y la puede corregir.

⚠️ Pendiente (fuera de este primer alcance): un distintivo visual tipo "🔗
Dinámica" para que se note a simple vista cuál valor llegó solo vs. cuál se
digitó a mano — requeriría agregar un campo a Medicion (no existe hoy en
trabajoparto, a diferencia de meows.Medicion.origen) más el cambio de
serializer/frontend correspondiente.

Ejecutar manualmente para probar:
    python manage.py sincronizar_frecuencia_fetal_dinamica --verbosity 2
"""
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand
from django.db.models import Max
from django.utils import timezone

from frecuenciafetal.sala_partos_db import listar_pacientes_sala_partos
from trabajoparto.models import (
    CampoParametro, EstadoFormulario, Formulario, Medicion, MedicionValor, Paciente, Parametro,
)

_RESPONSABLE_AUTO = 'Sincronización automática (Dinámica)'


def _a_numero(valor_texto):
    """Convierte '145' / '145,0' a Decimal. None si no aplica. Copia local
    del mismo parseo que usa meows/services/dinamica_signos_vitales.py — no
    se importa de ahí para no acoplar este módulo al de MEOWS."""
    if valor_texto is None:
        return None
    texto = str(valor_texto).strip().replace(",", ".")
    if not texto:
        return None
    try:
        return Decimal(texto)
    except InvalidOperation:
        return None

# Mismo OID que usa MEOWS para este signo vital — ver meows/services/
# dinamica_signos_vitales.py (docstring, mapeo confirmado contra Nexus).
_OID_FETOCARDIO = 20

_PARAMETRO_ID_FREC_CARD_FETAL = 8
_CAMPO_ID_VALOR = 6


class Command(BaseCommand):
    help = (
        'Sincroniza "Frecuencia Cardiaca Fetal" (card FETAL de Trabajo de Parto) '
        'desde Dinámica (FETOCARDIO), creando la hora de registro automáticamente.'
    )

    def handle(self, *args, **options):
        verbosity = options.get('verbosity', 1)

        try:
            parametro = Parametro.objects.get(id=_PARAMETRO_ID_FREC_CARD_FETAL)
            campo = CampoParametro.objects.get(id=_CAMPO_ID_VALOR)
        except (Parametro.DoesNotExist, CampoParametro.DoesNotExist) as e:
            self.stderr.write(self.style.ERROR(f'[ERR] Configuración de parámetro/campo no encontrada: {e}'))
            return

        pacientes_activos = listar_pacientes_sala_partos(limit=500)
        self.total_nuevas = 0

        for p in pacientes_activos:
            documento = (p.get('identificacion') or '').strip()
            folio = p.get('folio')
            if not documento or not folio:
                continue

            try:
                self._sincronizar_paciente(p, documento, folio, parametro, campo, verbosity)
            except Exception as e:
                # Una paciente con datos inconsistentes (ej. choque de historia
                # clínica) no debe tumbar la corrida completa -- las demás
                # pacientes activas siguen sincronizándose normalmente.
                self.stderr.write(self.style.ERROR(f'  [ERR] {documento}: {e}'))
                continue

        self.stdout.write(self.style.SUCCESS(
            f'[OK] {self.total_nuevas} hora(s) de registro nueva(s) creada(s) desde Dinámica.'
        ))

    def _sincronizar_paciente(self, p, documento, folio, parametro, campo, verbosity):
        paciente_tp = Paciente.objects.filter(num_identificacion=documento).first()
        if not paciente_tp:
            # Primera vez que esta paciente aparece en Trabajo de Parto:
            # se crea con los mismos datos mínimos (historia clínica,
            # nombres, fecha de nacimiento) que ya trae la lista de
            # activos de Sala de Partos — mismo origen que usa el resto
            # del HUB — para no duplicar consulta a Dinámica.
            historia_clinica = (p.get('historia_clinica') or '').strip()
            nombres = (p.get('nombre_paciente') or '').strip()
            if not historia_clinica or not nombres:
                if verbosity >= 2:
                    self.stdout.write(
                        f'  [SKIP] {documento}: faltan historia clínica o nombres '
                        f'en Sala de Partos, no se puede crear el paciente todavía.'
                    )
                return
            paciente_tp, _ = Paciente.objects.get_or_create(
                num_identificacion=documento,
                defaults={
                    'num_historia_clinica': historia_clinica,
                    'nombres': nombres,
                    'fecha_nacimiento': p.get('fecha_nacimiento'),
                },
            )

        formulario = (
            Formulario.objects.filter(paciente=paciente_tp)
            .order_by('-created_at')
            .first()
        )
        if not formulario:
            # Igual que con el paciente: se crea la hoja con lo mínimo
            # para poder adjuntar la lectura de FCF. `responsable` queda
            # marcado como automático a propósito -- la enfermera lo
            # reemplaza con su nombre real al guardar por primera vez a
            # mano (mismo formulario_id, vía PUT en guardarFormulario).
            formulario = Formulario.objects.create(
                paciente=paciente_tp,
                codigo='FRSPA-022',
                version='1',
                fecha_elabora=timezone.localdate(),
                num_hoja=1,
                estado=EstadoFormulario.G,
                responsable=_RESPONSABLE_AUTO,
                diagnostico=p.get('diagnostico') or None,
            )
            if verbosity >= 2:
                self.stdout.write(
                    f'  [+] Formulario #{formulario.id} auto-creado para {documento} '
                    f'({paciente_tp.nombres}) -- pendiente de completar por enfermería.'
                )

        ultima_hora = (
            Medicion.objects.filter(formulario=formulario, parametro=parametro)
            .aggregate(Max('tomada_en'))
            .get('tomada_en__max')
        )
        if ultima_hora is not None:
            # HCRHORREG en Dinámica es un datetime NAIVE en hora local (Bogotá).
            # `ultima_hora` sale del ORM como aware en UTC (USE_TZ=True) -- si se
            # compara tal cual contra la columna naive ("> 2026-09-11 12:00" contra
            # valores como "2026-09-11 07:30"), toda lectura nueva del mismo día
            # queda por debajo del corte y se pierde en silencio. Se convierte a
            # naive-local antes de usarla como filtro.
            ultima_hora = timezone.localtime(ultima_hora).replace(tzinfo=None)

        lecturas = _obtener_fetocardio_nuevo(folio, desde=ultima_hora)
        for hora, valor_texto in lecturas:
            valor_decimal = _a_numero(valor_texto)
            if valor_decimal is None:
                continue

            medicion, creada = Medicion.objects.get_or_create(
                formulario=formulario,
                parametro=parametro,
                tomada_en=hora,
            )
            MedicionValor.objects.update_or_create(
                medicion=medicion,
                campo=campo,
                defaults={'valor_number': valor_decimal, 'valor_text': None, 'valor_boolean': None},
            )
            if creada:
                self.total_nuevas += 1
                if verbosity >= 2:
                    self.stdout.write(
                        f'  + Frecuencia Cardiaca Fetal {valor_decimal} lpm para '
                        f'{documento} ({hora}), formulario #{formulario.id}'
                    )


def _obtener_fetocardio_nuevo(folio: int, desde=None):
    """
    Trae las lecturas de FETOCARDIO (OID 20) de Dinámica para un folio,
    opcionalmente solo las posteriores a `desde`. Devuelve una lista de
    tuplas (hora, valor_texto) ordenadas por hora ascendente.

    Reimplementado aparte de meows.services.dinamica_signos_vitales
    (que solo trae los campos que usa MEOWS) para no acoplar este módulo
    a la forma de diccionario que espera el motor MEOWS.
    """
    from django.db import connections

    with connections['readonly'].cursor() as cur:
        cur.execute("SELECT ADNINGRESO FROM HCNFOLIO WHERE OID = %s", [folio])
        fila = cur.fetchone()
        if not fila or fila[0] is None:
            return []
        adningreso = fila[0]

        sql = """
            SELECT sv.HCRHORREG, sv.HCSVALOR
            FROM HCNSIGVIT sv
            JOIN HCNREGENF re ON re.OID = sv.HCNREGENF
            WHERE re.ADNINGRESO = %s
              AND sv.HCNTIPSVIT = %s
        """
        params = [adningreso, _OID_FETOCARDIO]
        if desde is not None:
            sql += " AND sv.HCRHORREG > %s"
            params.append(desde)
        sql += " ORDER BY sv.HCRHORREG ASC"

        cur.execute(sql, params)
        return list(cur.fetchall())
