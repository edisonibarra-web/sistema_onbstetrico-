"""
2026-10-05: repara las mediciones de Dinámica importadas con el mapeo viejo
de OID de HCNTIPSVIT (ver meows/services/dinamica_signos_vitales.py): la
toma "ALERTA=GLASGOW 15" (OID 30) se guardaba como o2_req=15 y Glasgow
quedaba vacío; la de "24-39%" (OID 28) se guardaba como Glasgow.

Para cada medición con origen='dinamica' se vuelve a leer su toma en
Dinámica con el mapeo corregido y se reemplazan SOLO o2_req y glasgow; los
demás signos no se tocan. Luego se recalcula el MEOWS de la medición.

No dispara alertas: son tomas históricas, ya atendidas.

Uso:
    python manage.py reparar_glasgow_o2_dinamica            # solo muestra
    python manage.py reparar_glasgow_o2_dinamica --aplicar  # guarda
    (--desde AAAA-MM-DD limita por fecha de la toma; default 2026-09-01)
"""
from collections import defaultdict
from datetime import datetime

from django.core.management.base import BaseCommand
from django.db import connections, transaction
from django.utils import timezone

from meows.models import Medicion, MedicionValor, Parametro
from meows.services.dinamica_signos_vitales import _a_numero, obtener_signos_vitales_nuevos
from meows.services.meows import calcular_meows

CODIGOS = ('o2_req', 'glasgow')
LOTE_OIDS = 900  # SQL Server admite ~2100 parámetros por consulta


class Command(BaseCommand):
    help = 'Corrige Glasgow y % O2 de mediciones de Dinámica importadas con los OID viejos.'

    def add_arguments(self, parser):
        parser.add_argument('--aplicar', action='store_true', help='Guarda los cambios (sin esto solo los muestra).')
        parser.add_argument('--desde', default='2026-09-01', help='Fecha mínima de la toma (AAAA-MM-DD).')

    def handle(self, *args, **options):
        aplicar = options['aplicar']
        desde = timezone.make_aware(datetime.strptime(options['desde'], '%Y-%m-%d'))
        parametros = {p.codigo: p for p in Parametro.objects.filter(codigo__in=CODIGOS)}

        mediciones = list(
            Medicion.objects.filter(origen='dinamica', fecha_hora__gte=desde)
            .prefetch_related('valores__parametro')
        )
        self.stdout.write(f'{len(mediciones)} medición(es) de Dinámica desde {options["desde"]}.')

        # Ingreso (ADNINGRESO) de cada medición, a partir del OID de Dinámica
        # de cualquiera de sus valores.
        oid_por_medicion = {}
        for m in mediciones:
            oid = next((v.dinamica_oid for v in m.valores.all() if v.dinamica_oid), None)
            if oid:
                oid_por_medicion[m.id] = oid
        ingreso_por_oid = {}
        oids = list(set(oid_por_medicion.values()))
        with connections['readonly'].cursor() as cur:
            for i in range(0, len(oids), LOTE_OIDS):
                lote = oids[i:i + LOTE_OIDS]
                cur.execute(
                    f"""SELECT sv.OID, re.ADNINGRESO FROM HCNSIGVIT sv
                        JOIN HCNREGENF re ON re.OID = sv.HCNREGENF
                        WHERE sv.OID IN ({", ".join(["%s"] * len(lote))})""",
                    lote,
                )
                ingreso_por_oid.update(dict(cur.fetchall()))

        por_ingreso = defaultdict(list)
        sin_ingreso = 0
        for m in mediciones:
            ingreso = ingreso_por_oid.get(oid_por_medicion.get(m.id))
            if ingreso is None:
                sin_ingreso += 1
                continue
            por_ingreso[ingreso].append(m)

        revisadas = corregidas = 0
        for ingreso, lista in por_ingreso.items():
            hora_min = timezone.localtime(min(m.fecha_hora for m in lista)).replace(tzinfo=None)
            try:
                lecturas = obtener_signos_vitales_nuevos(None, desde=hora_min, ingreso_oid=ingreso)
            except Exception as e:
                self.stderr.write(self.style.WARNING(f'Ingreso {ingreso}: error consultando Dinámica ({e}); se omite.'))
                continue
            lectura_por_hora = {l['fecha_hora']: l for l in lecturas}

            for m in lista:
                lectura = lectura_por_hora.get(m.fecha_hora)
                if lectura is None:
                    continue
                revisadas += 1
                actuales = {v.parametro.codigo: v for v in m.valores.all() if v.parametro.codigo in CODIGOS}
                cambios = []
                for codigo in CODIGOS:
                    nuevo = lectura.get(codigo)
                    mv = actuales.get(codigo)
                    viejo = mv.valor if mv else None
                    nuevo_txt = str(nuevo) if nuevo is not None else None
                    if viejo != nuevo_txt:
                        cambios.append((codigo, mv, viejo, nuevo_txt, lectura['_oids'].get(codigo)))
                if not cambios:
                    continue
                corregidas += 1
                resumen = ', '.join(f'{c}: {v or "vacío"} -> {n or "vacío"}' for c, _, v, n, _ in cambios)
                if not aplicar:
                    self.stdout.write(f'  #{m.id} {m.paciente.numero_documento} {timezone.localtime(m.fecha_hora):%Y-%m-%d %H:%M} | {resumen}')
                    continue
                with transaction.atomic():
                    riesgo_antes = m.meows_riesgo
                    for codigo, mv, _, nuevo_txt, oid in cambios:
                        if nuevo_txt is None:
                            mv.delete()  # el valor salió del mapeo viejo, no existe en Dinámica
                        elif mv is None:
                            # 'todas': puede existir uno marcado como eliminado
                            # (unique_together medicion+parametro).
                            MedicionValor.todas.update_or_create(
                                medicion=m, parametro=parametros[codigo],
                                defaults={'valor': nuevo_txt, 'dinamica_oid': oid, 'eliminado_en': None},
                            )
                        else:
                            mv.valor, mv.dinamica_oid = nuevo_txt, oid
                            mv.save(update_fields=['valor', 'dinamica_oid'])
                    valores = list(MedicionValor.objects.filter(medicion=m).select_related('parametro'))
                    resultado = calcular_meows({
                        v.parametro.codigo: _a_numero(v.valor) for v in valores if _a_numero(v.valor) is not None
                    })
                    for v in valores:
                        puntaje = resultado['puntajes'].get(v.parametro.codigo)
                        if v.puntaje != puntaje:
                            v.puntaje = puntaje
                            v.save(update_fields=['puntaje'])
                    m.meows_total = resultado['meows_total']
                    m.meows_riesgo = resultado['meows_riesgo']
                    m.meows_mensaje = resultado['meows_mensaje']
                    m.save(update_fields=['meows_total', 'meows_riesgo', 'meows_mensaje'])
                self.stdout.write(f'  #{m.id} {resumen} | riesgo {riesgo_antes} -> {m.meows_riesgo}')

        accion = 'corregida(s)' if aplicar else 'por corregir (use --aplicar para guardar)'
        self.stdout.write(self.style.SUCCESS(
            f'[OK] {revisadas} revisada(s) contra Dinámica, {corregidas} {accion}; '
            f'{sin_ingreso} sin OID de Dinámica (no se pueden revisar).'
        ))
