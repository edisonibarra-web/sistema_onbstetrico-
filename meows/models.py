from django.conf import settings
from django.db import models
from django.utils import timezone
from datetime import date


# ============================================================================
# 0️⃣ MODELO EXTERNO: GENPACIEN (Base de datos ReadOnly)
# ============================================================================

class Genpacien(models.Model):
    OID = models.IntegerField(primary_key=True, db_column='OID')
    PACNUMDOC = models.CharField(max_length=20, db_column='PACNUMDOC')
    PACTIPDOC = models.IntegerField(db_column='PACTIPDOC')  # 1:CC, 2:TI, etc.
    PACPRINOM = models.CharField(max_length=100, db_column='PACPRINOM')
    PACSEGNOM = models.CharField(max_length=100, db_column='PACSEGNOM', null=True)
    PACPRIAPE = models.CharField(max_length=100, db_column='PACPRIAPE')
    PACSEGAPE = models.CharField(max_length=100, db_column='PACSEGAPE', null=True)
    GPAFECNAC = models.DateTimeField(db_column='GPAFECNAC')
    GPASEXPAC = models.IntegerField(db_column='GPASEXPAC')  # 1:M, 2:F (según convención usual, verificar)

    class Meta:
        managed = False
        db_table = 'Genpacien'
        verbose_name = "Paciente Externo (Genpacien)"

    def __str__(self):
        return f"{self.PACNUMDOC}"


# ============================================================================
# 1️⃣ MODELO PACIENTE
# ============================================================================
class Paciente(models.Model):
    # Campos persistentes (Solo lo que NO viene de Genpacien o es necesario para ordenamiento/cache)
    numero_documento = models.CharField(max_length=20, unique=True)
    nombres = models.CharField(max_length=150)
    apellidos = models.CharField(max_length=150)
    sexo = models.CharField(
        max_length=1,
        choices=[("F", "Femenino"), ("M", "Masculino")]
    )
    
    # Campos clínicos específicos de esta app
    aseguradora = models.CharField(max_length=200, blank=True, help_text="Nombre de la aseguradora")
    cama = models.CharField(max_length=50, blank=True, help_text="Número o código de cama")
    num_historia_clinica = models.CharField(max_length=50, blank=True, default="", help_text="Número de historia clínica")
    fecha_nacimiento = models.DateField(null=True, blank=True, help_text="Fecha de nacimiento del paciente")
    fecha_ingreso = models.DateField(null=True, blank=True, help_text="Fecha de ingreso al hospital")
    responsable = models.CharField(max_length=200, blank=True, help_text="Nombre del responsable del paciente")
    diagnostico = models.TextField(blank=True, default="", help_text="Diagnóstico clínico inicial")
    tipo_sangre = models.CharField(max_length=5, blank=True, help_text="Tipo de sangre (O+, A-, etc.)")
    nombre_acompanante = models.CharField(max_length=200, blank=True, help_text="Nombre del acompañante")
    edad_gestacional = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Edad gestacional en semanas")
    gestas = models.PositiveSmallIntegerField(null=True, blank=True, default=1, help_text="Número de gestas")
    n_controles_prenatales = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Número de controles prenatales")

    class Meta:
        verbose_name = "Paciente"
        verbose_name_plural = "Pacientes"
        ordering = ['apellidos', 'nombres']

    def __str__(self):
        return f"{self.numero_documento} - {self.nombres} {self.apellidos}"

    @property
    def info_externa(self):
        """Devuelve la instancia de Genpacien asociada, o None si la BD remota no está disponible."""
        # Cache por instancia para evitar múltiples consultas remotas
        # en una misma petición (edad, tipo_documento, fecha_nacimiento).
        if hasattr(self, "_info_externa_cache"):
            return self._info_externa_cache

        from django.conf import settings
        if not getattr(settings, 'HABILITAR_BD_EXTERNA', True):
            self._info_externa_cache = None
            return None

        if not self.numero_documento:
            self._info_externa_cache = None
            return None
        try:
            # 1. Intento con documento exacto
            ext = (
                Genpacien.objects.using('readonly')
                .filter(PACNUMDOC=self.numero_documento)
                .first()
            )
            if ext:
                self._info_externa_cache = ext
                return ext

            # 2. Intento limpiando ceros a la izquierda (muchas veces en Genpacien están sin ellos)
            doc_limpio = self.numero_documento.lstrip('0')
            if doc_limpio and doc_limpio != self.numero_documento:
                ext = (
                    Genpacien.objects.using('readonly')
                    .filter(PACNUMDOC=doc_limpio)
                    .first()
                )
                if ext:
                    self._info_externa_cache = ext
                    return ext
            
            # 3. Intento inverso: si el original no tiene ceros, buscar con terminación
            ext = (
                Genpacien.objects.using('readonly')
                .filter(PACNUMDOC__endswith=self.numero_documento)
                .first()
            )
            self._info_externa_cache = ext
            return ext
        except Exception:
            self._info_externa_cache = None
            return None


    @property
    def edad(self):
        """Calcula edad desde el campo local fecha_nacimiento."""
        fn = self.fecha_nacimiento
        if fn:
            today = date.today()
            return today.year - fn.year - ((today.month, today.day) < (fn.month, fn.day))
        return None

    @property
    def tipo_documento(self):
        """Mapea tipo de documento desde Genpacien."""
        ext = self.info_externa
        if ext:
            mapa_docs = {1: 'CC', 2: 'TI', 3: 'CE', 4: 'RC', 5: 'PA'}
            return mapa_docs.get(ext.PACTIPDOC, 'CC')
        return None

    def save(self, *args, **kwargs):
        # Si faltan nombres, intentar poblar (cachear nombres para búsquedas/ordenamiento)
        if not self.nombres:
            self.poblar_datos_basicos()
        super().save(*args, **kwargs)

    def poblar_datos_basicos(self):
        """Busca el paciente en la BD externa y llena nombres/sexo."""
        if not self.numero_documento:
            return

        try:
            ext = self.info_externa
            
            if ext:
                # Nombres
                seg_nom = f" {ext.PACSEGNOM}" if ext.PACSEGNOM else ""
                self.nombres = f"{ext.PACPRINOM}{seg_nom}".strip()
                
                # Apellidos
                seg_ape = f" {ext.PACSEGAPE}" if ext.PACSEGAPE else ""
                self.apellidos = f"{ext.PACPRIAPE}{seg_ape}".strip()
                
                # Sexo (Mapeo: 1=M, 2=F)
                if ext.GPASEXPAC == 1:
                    self.sexo = 'M'
                elif ext.GPASEXPAC == 2:
                    self.sexo = 'F'

                # Fecha de nacimiento
                if ext.GPAFECNAC:
                    self.fecha_nacimiento = ext.GPAFECNAC.date()

        except Exception:
            # Si no hay acceso a BD externa, mantener datos locales sin romper flujo.
            return





# ============================================================================
# 2️⃣ MODELO FORMULARIO
# ============================================================================
class Formulario(models.Model):
    codigo = models.CharField(max_length=30)
    nombre = models.CharField(max_length=150)
    descripcion = models.TextField(blank=True)
    version = models.CharField(max_length=20, default="1.0", help_text="Versión del formulario (ej: 1.0, 2.0)")
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Formulario"
        verbose_name_plural = "Formularios"
        ordering = ['nombre']
        unique_together = [('codigo', 'version')]

    def __str__(self):
        return f"{self.nombre} v{self.version}"


# ============================================================================
# 3️⃣ MODELO PARÁMETRO (Catálogo clínico genérico)
# ============================================================================
class Parametro(models.Model):
    codigo = models.CharField(max_length=30, unique=True)
    nombre = models.CharField(max_length=100)
    unidad = models.CharField(max_length=20)
    orden = models.PositiveIntegerField()
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Parámetro"
        verbose_name_plural = "Parámetros"
        ordering = ['orden']

    def __str__(self):
        return f"{self.codigo} - {self.nombre}"


# ============================================================================
# 4️⃣ MODELO MEDICIÓN (Cabecera de la toma)
# ============================================================================
class MedicionManager(models.Manager):
    """
    Manager por defecto de Medicion: excluye las marcadas como eliminadas en
    Dinámica (ver Medicion.eliminado_en, 2026-09-22). Se declara como el
    PRIMER manager para que también lo hereden los accesos inversos por FK
    (ej. paciente.mediciones.all(), atencion.mediciones_meows.all()) -- así
    una medición "borrada" desaparece de verdad en todas partes (Línea de
    Tiempo, PDF, alertas, conteos), sin tener que tocar cada vista una por
    una y arriesgarse a dejar alguna sin actualizar.

    Antes de que existiera eliminado_en, todas las filas ya guardadas tenían
    ese campo en NULL -- agregar este filtro no cambia nada del
    comportamiento anterior para ningún dato existente, solo empieza a
    ocultar lo que de ahora en adelante se detecte borrado en Dinámica.

    Para ver también lo eliminado (uso interno: el propio job de
    sincronización, que necesita revisar si algo reapareció en Dinámica
    para restaurarlo) usar Medicion.todas.
    """
    def get_queryset(self):
        return super().get_queryset().filter(eliminado_en__isnull=True)


class Medicion(models.Model):
    atencion = models.ForeignKey(
        "obstetricia.AtencionParto",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="mediciones_meows",
    )
    paciente = models.ForeignKey(
        Paciente,
        on_delete=models.CASCADE,
        related_name="mediciones"
    )
    formulario = models.ForeignKey(
        Formulario,
        on_delete=models.CASCADE,
        related_name="mediciones"
    )
    fecha_hora = models.DateTimeField(
        default=timezone.now,
        help_text="Fecha y hora real del monitoreo, registrada manualmente."
    )

    origen = models.CharField(
        max_length=10,
        default="manual",
        choices=[
            ("manual", "Manual"),
            ("dinamica", "Dinámica"),
            # 2026-09-18: triaje -- signos vitales tomados ANTES de que la
            # paciente tenga ingreso formal en Dinámica (sin Adningreso no
            # hay Hcnfolio, así que Dinámica no tiene nada que sincronizar
            # todavía). Flujo separado, nunca se mezcla con 'dinamica' -- ver
            # crear_medicion_triaje / api_alertas_pendientes_triaje.
            ("triaje", "Triaje"),
        ],
        help_text="Si la medición se digitó a mano, se tomó en triaje (sin ingreso aún) o se importó automáticamente desde Dinámica.",
    )
    dinamica_folio = models.IntegerField(
        null=True, blank=True,
        help_text="HCNFOLIO.OID de Dinámica del que se importó esta medición (solo si origen='dinamica').",
    )
    # 2026-09-14: a pedido explícito -- el responsable real de una toma
    # importada de Dinámica es quien la digitó ALLÁ (HCNSIGVIT.GENMEDICO), no
    # necesariamente la persona logeada en esta app en ese momento (puede ser
    # una enfermera distinta con turno abierto acá mientras otra diligencia
    # en Dinámica). Se trae desde GENMEDICO.GMENOMCOM -- ver
    # meows/services/dinamica_signos_vitales.py. Queda null en mediciones
    # manuales (origen='manual'): esas sí las diligencia quien tiene la
    # sesión abierta acá.
    responsable_dinamica = models.CharField(
        max_length=255, null=True, blank=True,
        help_text="Nombre de quien digitó esta toma en Dinámica (GENMEDICO.GMENOMCOM). "
                   "Solo aplica a mediciones origen='dinamica'.",
    )
    # 2026-09-23: quien registró la toma EN ESTA APP (profesional en sesión,
    # nombre_profesional_sesion) -- hoy solo lo llena Triaje, que se digita
    # aquí antes de que exista ingreso en Dinámica. Se fija al crear la toma
    # y no cambia si otra persona la corrige después. Null en tomas de
    # triaje registradas antes de existir este campo.
    registrado_por = models.CharField(
        max_length=255, null=True, blank=True,
        help_text="Profesional en sesión que registró esta toma en la app (Triaje).",
    )

    @property
    def responsable_toma(self):
        """Quién hizo la toma: quien la digitó en Dinámica o, si se registró
        en esta app (Triaje), quien la registró aquí."""
        return self.responsable_dinamica or self.registrado_por or ''
    alerta_pendiente = models.BooleanField(
        default=False,
        help_text="True si esta medición generó una alerta MEOWS (riesgo alto/medio).",
    )
    alerta_generada_en = models.DateTimeField(
        null=True, blank=True,
        help_text="Momento en que se disparó la alerta — usado para la ventana de "
                   "notificación del sidebar (ver api_alertas_pendientes en views.py). "
                   "No es lo mismo que fecha_hora, que es cuándo se tomó el signo vital.",
    )
    # "Visto" COMPARTIDO entre equipos/usuarios: antes solo vivía en el
    # sessionStorage del navegador que abría el detalle, así que la misma
    # alerta reaparecía como nueva en cualquier otra pestaña/PC. Al marcarse
    # aquí (ver marcar_alerta_vista en views.py, llamado desde la vista de
    # resultado), api_alertas_pendientes deja de devolverla para TODOS —
    # decisión 2026-09-08: ver el detalle de una alerta la da por atendida
    # para todo el mundo, no solo para quien la abrió.
    alerta_vista_en = models.DateTimeField(null=True, blank=True)
    alerta_vista_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="alertas_meows_vistas",
    )

    # 🧠 RESULTADOS MEOWS (se llenan luego)
    meows_total = models.PositiveIntegerField(null=True, blank=True)
    meows_riesgo = models.CharField(
        max_length=10,
        null=True,
        blank=True,
        choices=[
            ("BLANCO", "Blanco"),
            ("VERDE", "Verde"),
            ("AMARILLO", "Amarillo"),
            ("ROJO", "Rojo"),
        ]
    )
    meows_mensaje = models.TextField(null=True, blank=True)

    # 2026-09-21: momento de la última corrección detectada de un valor ya
    # sincronizado (ver sincronizar_signos_vitales_dinamica.py) -- señal
    # SEPARADA de alerta_generada_en (esa solo se llena en riesgo
    # Amarillo/Rojo). Se usa para que la Línea de Tiempo Clínica abierta de
    # esa paciente se refresque sola aunque la corrección no dispare
    # alerta -- ver api_correcciones_recientes en views.py.
    ultima_correccion_en = models.DateTimeField(null=True, blank=True)

    # 2026-09-22: borrado suave -- si esta medición (origen='dinamica') deja
    # de existir en Dinámica (alguien la borró allá), se marca aquí en vez
    # de eliminarse de verdad: desaparece de todas las vistas (ver
    # MedicionManager arriba), pero el dato queda recuperable por si el
    # "borrado" resultó ser un problema pasajero de la consulta a Nexus en
    # vez de una eliminación real. Si la toma reaparece en una corrida
    # posterior del sincronizador, este campo se limpia solo (se
    # "restaura") -- ver sincronizar_signos_vitales_dinamica.py.
    eliminado_en = models.DateTimeField(null=True, blank=True, db_index=True)

    objects = MedicionManager()
    todas = models.Manager()  # incluye eliminadas -- uso interno (sync/admin/debug)

    class Meta:
        verbose_name = "Medición"
        verbose_name_plural = "Mediciones"
        ordering = ['-fecha_hora']
        # 'todas' (sin filtrar) como manager base: así una cascada de borrado
        # real (ej. Paciente.delete()) sigue encontrando y limpiando también
        # las mediciones marcadas como eliminadas, y no las deja huérfanas.
        base_manager_name = 'todas'

    def __str__(self):
        return f"Medición {self.id} - {self.fecha_hora}"


# ============================================================================
# 5️⃣ MODELO MEDICIÓN VALOR (Detalle por parámetro)
# ============================================================================
class MedicionValorManager(models.Manager):
    """Mismo criterio que MedicionManager (ver arriba), pero para ocultar un
    solo valor puntual (ej. solo la temperatura) sin tener que marcar toda
    la medición como eliminada, cuando en Dinámica desapareció ese dato
    puntual pero el resto de la toma sigue existiendo."""
    def get_queryset(self):
        return super().get_queryset().filter(eliminado_en__isnull=True)


class MedicionValor(models.Model):
    medicion = models.ForeignKey(
        Medicion,
        on_delete=models.CASCADE,
        related_name="valores"
    )
    parametro = models.ForeignKey(
        Parametro,
        on_delete=models.PROTECT
    )
    valor = models.CharField(max_length=20)
    puntaje = models.PositiveSmallIntegerField(null=True, blank=True)
    # 2026-09-21: OID de HCNSIGVIT (Dinámica) del que vino este valor -- solo
    # se llena para origen='dinamica' (ver Medicion.origen). Permite detectar
    # cuando alguien EDITA el valor de una toma ya sincronizada en Dinámica
    # (antes era invisible: el sync solo miraba HCRHORREG > última importada,
    # nunca volvía a mirar una fila ya traída) -- ver
    # meows/management/commands/sincronizar_signos_vitales_dinamica.py.
    dinamica_oid = models.IntegerField(null=True, blank=True, db_index=True)
    # 2026-09-22: borrado suave -- ver MedicionValorManager y el mismo campo
    # en Medicion. Se marca cuando este valor puntual (no toda la toma) deja
    # de existir en Dinámica.
    eliminado_en = models.DateTimeField(null=True, blank=True, db_index=True)

    objects = MedicionValorManager()
    todas = models.Manager()  # incluye eliminados -- uso interno (sync/admin/debug)

    class Meta:
        verbose_name = "Valor de Medición"
        verbose_name_plural = "Valores de Medición"
        unique_together = ("medicion", "parametro")
        ordering = ['parametro__orden']
        base_manager_name = 'todas'

    def __str__(self):
        return f"{self.parametro.codigo}: {self.valor}"


# ============================================================================
# 6️⃣ MODELO RANGO PARÁMETRO (Rangos de valores para cálculo de scores)
# ============================================================================
class RangoParametro(models.Model):
    """
    Define los rangos de valores y sus scores asociados para cada parámetro.
    Permite cambiar reglas sin modificar código.
    """
    parametro = models.ForeignKey(
        Parametro,
        on_delete=models.CASCADE,
        related_name="rangos"
    )
    valor_min = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Valor mínimo del rango (inclusive)"
    )
    valor_max = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Valor máximo del rango (inclusive)"
    )
    score = models.PositiveSmallIntegerField(
        help_text="Puntaje asignado a este rango (0-3)"
    )
    orden = models.PositiveIntegerField(
        default=0,
        help_text="Orden de evaluación (menor a mayor)"
    )
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Rango de Parámetro"
        verbose_name_plural = "Rangos de Parámetros"
        ordering = ['parametro', 'orden', 'valor_min']
        indexes = [
            models.Index(fields=['parametro', 'activo', 'orden']),
        ]

    def __str__(self):
        return f"{self.parametro.codigo}: [{self.valor_min}-{self.valor_max}] = {self.score}"

    def contiene_valor(self, valor: float) -> bool:
        """Verifica si un valor está dentro de este rango."""
        return self.valor_min <= valor <= self.valor_max


# ============================================================================
# MODELO LEGACY: ParametroMEOWS (mantener por compatibilidad)
# ============================================================================
class ParametroMEOWS(models.Model):
    codigo = models.CharField(max_length=30, unique=True)
    nombre = models.CharField(max_length=100)
    unidad = models.CharField(max_length=20)
    orden = models.PositiveIntegerField()

    class Meta:
        verbose_name = "Parámetro MEOWS"
        verbose_name_plural = "Parámetros MEOWS"
        ordering = ['orden']

    def __str__(self):
        return f"{self.codigo} - {self.nombre}"


# ============================================================================
# 7️⃣ MODELOS EXTERNOS ADICIONALES (ReadOnly - DGEMPRES99)
# ============================================================================

class Gendiagno(models.Model):
    OID = models.IntegerField(primary_key=True, db_column='OID')
    DIACODIGO = models.CharField(max_length=20, db_column='DIACODIGO')
    DIANOMBRE = models.CharField(max_length=500, db_column='DIANOMBRE')

    class Meta:
        managed = False
        db_table = 'GENDIAGNO'
        verbose_name = "Diagnóstico (Gendiagno)"

    def __str__(self):
        return f"{self.DIACODIGO} - {self.DIANOMBRE}"

class Gendetcon(models.Model):
    OID = models.IntegerField(primary_key=True, db_column='OID')
    GDECODIGO = models.CharField(max_length=50, db_column='GDECODIGO')
    GDENOMBRE = models.CharField(max_length=200, db_column='GDENOMBRE')

    class Meta:
        managed = False
        db_table = 'GENDETCON'

    def __str__(self):
        return f"{self.GDENOMBRE}"

class Hpngrupos(models.Model):
    OID = models.IntegerField(primary_key=True, db_column='OID')
    HGRCODIGO = models.CharField(max_length=50, db_column='HGRCODIGO')
    HGRNOMBRE = models.CharField(max_length=200, db_column='HGRNOMBRE')

    class Meta:
        managed = False
        db_table = 'HPNGRUPOS'

    def __str__(self):
        return self.HGRNOMBRE

class Hpnsubgru(models.Model):
    OID = models.IntegerField(primary_key=True, db_column='OID')
    HSUCODIGO = models.CharField(max_length=50, db_column='HSUCODIGO')
    HSUNOMBRE = models.CharField(max_length=200, db_column='HSUNOMBRE')
    HGRGRUPO = models.ForeignKey(Hpngrupos, models.DO_NOTHING, db_column='HGRGRUPO', null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'HPNSUBGRU'

    def __str__(self):
        return self.HSUNOMBRE

class Hpndefcam(models.Model):
    OID = models.IntegerField(primary_key=True, db_column='OID')
    HCACODIGO = models.CharField(max_length=50, db_column='HCACODIGO')
    HCANOMBRE = models.CharField(max_length=200, db_column='HCANOMBRE')
    HPNGRUPOS = models.ForeignKey(Hpngrupos, models.DO_NOTHING, db_column='HPNGRUPOS', null=True, blank=True)
    HPNSUBGRU = models.ForeignKey(Hpnsubgru, models.DO_NOTHING, db_column='HPNSUBGRU', null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'HPNDEFCAM'
        verbose_name = "Cama (Hpndefcam)"

    def __str__(self):
        return self.HCANOMBRE

class Adningreso(models.Model):
    OID = models.IntegerField(primary_key=True, db_column='OID')
    AINCONSEC = models.IntegerField(db_column='AINCONSEC')
    GENPACIEN = models.ForeignKey(Genpacien, models.DO_NOTHING, db_column='GENPACIEN', related_name='ingresos')
    AINFECING = models.DateTimeField(db_column='AINFECING', null=True, blank=True)
    AINESTADO = models.IntegerField(db_column='AINESTADO', null=True, blank=True)
    GENDETCON = models.ForeignKey(Gendetcon, models.DO_NOTHING, db_column='GENDETCON', null=True, blank=True)
    HPNDEFCAM = models.ForeignKey(Hpndefcam, models.DO_NOTHING, db_column='HPNDEFCAM', null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'ADNINGRESO'
        verbose_name = "Ingreso (Adningreso)"

    def __str__(self):
        return f"Ingreso {self.AINCONSEC}"

class Hpnestanc(models.Model):
    OID = models.IntegerField(primary_key=True, db_column='OID')
    ADNINGRES = models.ForeignKey(Adningreso, models.DO_NOTHING, db_column='ADNINGRES', related_name='estancias')
    HPNDEFCAM = models.ForeignKey(Hpndefcam, models.DO_NOTHING, db_column='HPNDEFCAM', related_name='estancias')
    HESFECING = models.DateTimeField(db_column='HESFECING', null=True, blank=True)
    HESFECSAL = models.DateTimeField(db_column='HESFECSAL', null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'HPNESTANC'

class Hcnfolio(models.Model):
    OID = models.IntegerField(primary_key=True, db_column='OID')
    HCNUMFOL = models.IntegerField(db_column='HCNUMFOL')
    HCFECFOL = models.DateTimeField(db_column='HCFECFOL', null=True, blank=True)
    GENPACIEN = models.ForeignKey(Genpacien, models.DO_NOTHING, db_column='GENPACIEN', related_name='folios')
    ADNINGRESO = models.ForeignKey(Adningreso, models.DO_NOTHING, db_column='ADNINGRESO', related_name='folios')

    class Meta:
        managed = False
        db_table = 'HCNFOLIO'
        verbose_name = "Folio Clínico"

    def __str__(self):
        return f"Folio {self.HCNUMFOL}"

class Hcndiapac(models.Model):
    OID = models.IntegerField(primary_key=True, db_column='OID')
    HCNFOLIO = models.ForeignKey(Hcnfolio, models.DO_NOTHING, db_column='HCNFOLIO', related_name='diagnosticos')
    GENDIAGNO = models.ForeignKey(Gendiagno, models.DO_NOTHING, db_column='GENDIAGNO')
    HCPDIAPRIN = models.IntegerField(db_column='HCPDIAPRIN', null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'HCNDIAPAC'

class Hcmwingin(models.Model):
    OID = models.IntegerField(primary_key=True, db_column='OID')
    HCNFOLIO = models.ForeignKey(Hcnfolio, models.DO_NOTHING, db_column='HCNFOLIO')
    # Tabla extensa

    class Meta:
        managed = False
        db_table = 'HCMWINGIN'

