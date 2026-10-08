from rest_framework import serializers
from .models import (
    RegistroParto, ControlFetocardia, ControlRecienNacido,
    GlucometriaRecienNacido, ControlPostpartoInmediato, ControlSangrado,
    ControlGlobo, ControlSutura, recalcular_estados_sangrado,
)
from obstetriciaunificador.models import AtencionParto


class AtencionToleranteField(serializers.PrimaryKeyRelatedField):
    """
    2026-09-22: 'atencion' es un vínculo interno de enrutamiento (fila de
    AtencionParto, sin valor clínico por sí misma -- ver el mismo criterio
    ya aplicado al ocultar "ID de Atención" en la card de Sala de Partos),
    no un dato clínico. El autoguardado silencioso de Control Posparto
    Inmediato lo manda tal cual venga en la URL (?atencion=<id>); si ese id
    ya no existe (enlace viejo, entorno con datos distintos, etc.), antes se
    rechazaba TODO el guardado del registro -- perdiendo datos clínicos
    reales (fetocardia, sangrado, etc.) por culpa de un id de enrutamiento
    inválido. Ahora, si el id no existe, se guarda como si no hubiera
    llegado ninguno (atencion=None) en vez de fallar el registro completo.

    Solo se perdona el código "does_not_exist" -- un id bien formado que no
    existe. Cualquier otro error (ej. un valor mal formado, que no es ni
    siquiera un id válido) se sigue rechazando: eso sí es un dato corrupto,
    no una referencia obsoleta, y no debe ocultarse.
    """
    def to_internal_value(self, data):
        try:
            return super().to_internal_value(data)
        except serializers.ValidationError as exc:
            if exc.detail and exc.detail[0].code == "does_not_exist":
                return None
            raise


# 2026-09-28: los campos de firma (quién registró) los pone SOLO el servidor
# con el profesional en sesión -- nunca se aceptan del cliente.
CAMPOS_FIRMA = ['registrado_por', 'registrado_en']


class ControlFetocardiaSerializer(serializers.ModelSerializer):
    class Meta:
        model = ControlFetocardia
        fields = '__all__'
        read_only_fields = ['registro', 'responsable'] + CAMPOS_FIRMA


class GlucometriaSerializer(serializers.ModelSerializer):
    class Meta:
        model = GlucometriaRecienNacido
        fields = '__all__'
        read_only_fields = ['control_rn']


def aplicar_delta_glucometrias(rn, agregar, quitar):
    """2026-10-06: el formulario ya no manda la lista completa de
    glucometrías (reemplazarla borraba las que otra pantalla había agregado
    mientras tanto): manda solo las que agregó y las que quitó. Agregar una
    que ya existe (misma hora y resultado) no la duplica, así un reintento o
    dos pantallas registrando la misma toma no crean copias."""
    for g in quitar or []:
        existente = rn.glucometrias.filter(hora=g['hora'], resultado=g['resultado']).order_by('id').first()
        if existente is not None:
            existente.delete()
    for g in agregar or []:
        if not rn.glucometrias.filter(hora=g['hora'], resultado=g['resultado']).exists():
            GlucometriaRecienNacido.objects.create(control_rn=rn, hora=g['hora'], resultado=g['resultado'])


class ControlRecienNacidoSerializer(serializers.ModelSerializer):
    glucometrias = GlucometriaSerializer(many=True, required=False)
    # 2026-10-06: cambios de la lista en vez de la lista completa (ver aplicar_delta_glucometrias).
    glucometrias_agregar = GlucometriaSerializer(many=True, required=False, write_only=True)
    glucometrias_quitar = GlucometriaSerializer(many=True, required=False, write_only=True)
    # 2026-09-30: la huella (PDF) solo se sube/quita por su propio endpoint
    # (RegistroPartoViewSet.huella_rn) -- el autoguardado nunca la toca, y
    # la ruta del archivo en disco no se expone.
    tiene_huella = serializers.SerializerMethodField()

    class Meta:
        model = ControlRecienNacido
        exclude = ['huella_pdf']
        read_only_fields = ['registro', 'huella_subida_por', 'huella_subida_en'] + CAMPOS_FIRMA

    def get_tiene_huella(self, obj):
        return bool(obj.huella_pdf)

    def validate(self, attrs):
        for campo in ('apgar_1min', 'apgar_5min', 'apgar_10min'):
            valor = attrs.get(campo)
            if valor is not None and not 0 <= valor <= 10:
                raise serializers.ValidationError({campo: 'El APGAR debe estar entre 0 y 10.'})
        return attrs

    def create(self, validated_data):
        glucometrias_data = validated_data.pop('glucometrias', [])
        agregar = validated_data.pop('glucometrias_agregar', None)
        quitar = validated_data.pop('glucometrias_quitar', None)
        control_rn = ControlRecienNacido.objects.create(**validated_data)
        for glucometria_data in glucometrias_data:
            GlucometriaRecienNacido.objects.create(control_rn=control_rn, **glucometria_data)
        aplicar_delta_glucometrias(control_rn, agregar, quitar)
        return control_rn

    def update(self, instance, validated_data):
        glucometrias_data = validated_data.pop('glucometrias', None)
        agregar = validated_data.pop('glucometrias_agregar', None)
        quitar = validated_data.pop('glucometrias_quitar', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        if glucometrias_data is not None:
            instance.glucometrias.all().delete()
            for glucometria_data in glucometrias_data:
                GlucometriaRecienNacido.objects.create(control_rn=instance, **glucometria_data)
        aplicar_delta_glucometrias(instance, agregar, quitar)
        return instance


class ControlPostpartoSerializer(serializers.ModelSerializer):
    class Meta:
        model = ControlPostpartoInmediato
        fields = '__all__'
        read_only_fields = ['registro', 'responsable'] + CAMPOS_FIRMA


class MinutoUnicoPorRegistroMixin:
    """2026-10-06: un solo control por minuto del cronograma en cada registro
    (unique_together registro/minuto_control). DRF no lo valida solo porque
    `registro` es de solo lectura: un duplicado (dos tablets sobre la misma
    paciente, o un reintento) reventaba con IntegrityError (500) y la
    pantalla no sabía por qué. Ahora es un 400 con código 'minuto_ocupado',
    que el formulario usa para resincronizar los controles."""

    def validate(self, attrs):
        attrs = super().validate(attrs)
        view = self.context.get('view')
        registro_id = getattr(view, 'kwargs', {}).get('registro_pk') if view else None
        minuto = attrs.get('minuto_control', getattr(self.instance, 'minuto_control', None))
        if registro_id and minuto is not None:
            existentes = self.Meta.model.objects.filter(registro_id=registro_id, minuto_control=minuto)
            if self.instance is not None:
                existentes = existentes.exclude(pk=self.instance.pk)
            if existentes.exists():
                raise serializers.ValidationError(
                    {'minuto_control': f'El control del minuto {minuto} ya está registrado.'},
                    code='minuto_ocupado',
                )
        return attrs


class ControlSangradoSerializer(MinutoUnicoPorRegistroMixin, serializers.ModelSerializer):
    class Meta:
        model = ControlSangrado
        fields = '__all__'
        # `estado` (semáforo) se calcula en el backend -- ver
        # `recalcular_estados_sangrado` en models.py -- nunca lo manda el cliente.
        read_only_fields = ['registro', 'estado'] + CAMPOS_FIRMA

    def validate_detalle(self, valor):
        """2026-10-08: el detalle de materiales/pesajes es un objeto pequeño."""
        import json
        if valor is None:
            return None
        if not isinstance(valor, dict):
            raise serializers.ValidationError('El detalle debe ser un objeto.')
        if len(json.dumps(valor)) > 20000:
            raise serializers.ValidationError('El detalle es demasiado grande.')
        # 2026-10-08: el control siguiente resta este peso ("mismo pañal"):
        # un error de digitación (p. ej. 87878 gr) dejaba en 0 cc los siguientes.
        panal = valor.get('panal') or {}
        for pesaje in (panal.get('pesajes') or []) if isinstance(panal, dict) else []:
            try:
                peso = float((pesaje or {}).get('peso') or 0)
            except (TypeError, ValueError, AttributeError):
                raise serializers.ValidationError('Peso del pañal inválido.')
            if peso < 0 or peso > 2000:
                raise serializers.ValidationError('El peso del pañal debe estar entre 0 y 2000 gr.')
        return valor


class ControlGloboSerializer(MinutoUnicoPorRegistroMixin, serializers.ModelSerializer):
    class Meta:
        model = ControlGlobo
        fields = '__all__'
        read_only_fields = ['registro'] + CAMPOS_FIRMA


class ControlSuturaSerializer(MinutoUnicoPorRegistroMixin, serializers.ModelSerializer):
    class Meta:
        model = ControlSutura
        fields = '__all__'
        read_only_fields = ['registro'] + CAMPOS_FIRMA


# 2026-09-22: una vez que el registro tiene completado_en (se cerró con
# "Guardar Registro Completo"), solo estos campos siguen pudiéndose
# corregir -- son exactamente los que la Vista Previa del formulario sabe
# editar (características del parto y vigilancia posparto inmediato). El
# resto del payload de una actualización posterior (autoguardado que
# alcance a dispararse, u otro intento) se ignora en silencio en vez de
# rechazar la petición completa -- así no hace falta que el cliente avise
# "esto viene de la Vista Previa": cualquier cambio a un campo no listado
# aquí simplemente no tiene efecto mientras el registro esté cerrado.
CAMPOS_EDITABLES_POST_CIERRE = {
    'tipo_parto', 'episiotomia', 'tipo_alumbramiento', 'hora_parto',
    'globo_seguridad', 'sutura_heridas', 'sangrado_cuantificado_cc',
    # 2026-10-05: la Vista Previa ahora también corrige estos (datos de la
    # paciente y desgarro). Nombre e identificación NO: vienen de Dinámica.
    'desgarro', 'desgarro_subgrado', 'edad_gestacional', 'gestas', 'nombre_acompanante',
}
# 2026-10-05: el Control del recién nacido también se corrige desde la Vista
# Previa con el registro cerrado, pero estos campos (obligatorios para cerrar,
# ver CAMPOS_RN_OBLIGATORIOS_CIERRE en views.py) no se pueden dejar vacíos:
# un vacío en la corrección conserva el valor que ya tenía.
CAMPOS_RN_NO_VACIAR_POST_CIERRE = ('genero', 'peso', 'talla', 'apgar_1min', 'apgar_5min')


class RegistroPartoSerializer(serializers.ModelSerializer):
    atencion = AtencionToleranteField(
        queryset=AtencionParto.objects.all(), required=False, allow_null=True
    )
    controles_fetocardia = ControlFetocardiaSerializer(many=True, required=False)
    control_recien_nacido = ControlRecienNacidoSerializer(required=False)
    controles_postparto = ControlPostpartoSerializer(many=True, required=False)
    controles_sangrado = ControlSangradoSerializer(many=True, required=False)
    controles_globo = ControlGloboSerializer(many=True, required=False)
    controles_sutura = ControlSuturaSerializer(many=True, required=False)
    # 2026-09-28: quiénes diligenciaron el registro y qué hizo cada uno.
    responsables = serializers.SerializerMethodField()
    # 2026-10-06: responsables de cada paso (Fetocardia, Parto, Vigilancia, RN).
    responsables_secciones = serializers.SerializerMethodField()

    class Meta:
        model = RegistroParto
        fields = '__all__'
        # Solo la vista (RegistroPartoViewSet, al recibir el flag "completar"
        # del botón "Guardar Registro Completo") puede escribir estos dos --
        # nunca directo desde el payload de un guardado normal.
        # 2026-09-28: el responsable ya no se escribe a mano: lo pone el
        # servidor (creado_por + participaciones, ver responsables.py).
        read_only_fields = ['completado_en', 'completado_por', 'creado_por', 'nombre_firma_paciente']

    def get_responsables(self, obj):
        from .responsables import responsables_para_api
        return responsables_para_api(obj)

    def get_responsables_secciones(self, obj):
        from .responsables import responsables_por_seccion
        return responsables_por_seccion(obj)

    def _firma(self, con_responsable=False):
        from .responsables import firma_sesion
        return firma_sesion(self.context.get('request'), con_responsable=con_responsable)

    def create(self, validated_data):
        fetocardia_data = validated_data.pop('controles_fetocardia', []) or []
        rn_data = validated_data.pop('control_recien_nacido', None)
        postparto_data = validated_data.pop('controles_postparto', []) or []
        sangrado_data = validated_data.pop('controles_sangrado', []) or []
        globo_data = validated_data.pop('controles_globo', []) or []
        sutura_data = validated_data.pop('controles_sutura', []) or []

        firma = self._firma()
        validated_data['creado_por'] = firma['registrado_por']
        registro = RegistroParto.objects.create(**validated_data)

        for fc in fetocardia_data:
            fc_dict = dict(fc) if hasattr(fc, 'items') else fc
            fc_clean = {
                'fecha': fc_dict.get('fecha'),
                'hora': fc_dict.get('hora'),
                'fetocardia': fc_dict.get('fetocardia'),
            }
            if fc_clean['fecha'] is not None and fc_clean['hora'] is not None and fc_clean['fetocardia'] is not None:
                ControlFetocardia.objects.create(registro=registro, **fc_clean, **self._firma(con_responsable=True))

        if rn_data:
            glucometrias = rn_data.pop('glucometrias', [])
            agregar = rn_data.pop('glucometrias_agregar', None)
            quitar = rn_data.pop('glucometrias_quitar', None)
            rn = ControlRecienNacido.objects.create(registro=registro, **rn_data, **firma)
            for g in glucometrias:
                GlucometriaRecienNacido.objects.create(control_rn=rn, **g)
            aplicar_delta_glucometrias(rn, agregar, quitar)

        for cp in postparto_data:
            cp = {k: v for k, v in dict(cp).items() if k != 'responsable'}
            ControlPostpartoInmediato.objects.create(registro=registro, **cp, **self._firma(con_responsable=True))

        for sc in sangrado_data:
            ControlSangrado.objects.create(registro=registro, **sc, **firma)
        if sangrado_data:
            recalcular_estados_sangrado(registro)

        for cg in globo_data:
            ControlGlobo.objects.create(registro=registro, **cg, **firma)

        for cs in sutura_data:
            ControlSutura.objects.create(registro=registro, **cs, **firma)

        return registro

    def _guardar_recien_nacido(self, instance, rn_data):
        glucometrias = rn_data.pop('glucometrias', None)
        agregar = rn_data.pop('glucometrias_agregar', None)
        quitar = rn_data.pop('glucometrias_quitar', None)
        rn, creado = ControlRecienNacido.objects.update_or_create(
            registro=instance, defaults=rn_data
        )
        if creado or not rn.registrado_por:
            firma = self._firma()
            ControlRecienNacido.objects.filter(pk=rn.pk).update(**firma)
            # rn queda en caché en instance.control_recien_nacido: sin
            # esto, la respuesta salía sin la firma recién guardada.
            for campo, valor in firma.items():
                setattr(rn, campo, valor)
        aplicar_delta_glucometrias(rn, agregar, quitar)
        if glucometrias is None:
            return  # no vinieron: se conservan las que hay
        # 2026-09-30: el autoguardado reenvía el recién nacido completo
        # cada vez -- las glucometrías solo se reescriben si cambiaron.
        actuales = [(g.hora, g.resultado) for g in rn.glucometrias.order_by('hora', 'id')]
        nuevas = sorted((g['hora'], g['resultado']) for g in glucometrias)
        if actuales != nuevas:
            rn.glucometrias.all().delete()
            for g in glucometrias:
                GlucometriaRecienNacido.objects.create(control_rn=rn, **g)

    def update(self, instance, validated_data):
        if instance.completado_en is not None:
            # Registro cerrado -- ver CAMPOS_EDITABLES_POST_CIERRE arriba.
            # No se tocan controles anidados (fetocardia/postparto/
            # sangrado/globo/sutura) desde aquí; el recién nacido sí
            # (2026-10-05), sin vaciar sus obligatorios de cierre.
            rn_data = validated_data.pop('control_recien_nacido', None)
            for attr, value in validated_data.items():
                if attr in CAMPOS_EDITABLES_POST_CIERRE:
                    setattr(instance, attr, value)
            instance.save()
            if rn_data is not None:
                rn_data = {
                    k: v for k, v in rn_data.items()
                    if not (k in CAMPOS_RN_NO_VACIAR_POST_CIERRE and v in (None, ''))
                }
                self._guardar_recien_nacido(instance, rn_data)
            return instance

        fetocardia_data = validated_data.pop('controles_fetocardia', None)
        rn_data = validated_data.pop('control_recien_nacido', None)
        postparto_data = validated_data.pop('controles_postparto', None)
        sangrado_data = validated_data.pop('controles_sangrado', None)
        globo_data = validated_data.pop('controles_globo', None)
        sutura_data = validated_data.pop('controles_sutura', None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if fetocardia_data is not None:
            # El PUT principal del registro nunca reemplaza los controles de
            # fetocardia en bloque; se agregan/corrigen uno por uno a través
            # del endpoint anidado dedicado (ControlFetocardiaViewSet).
            pass
        if rn_data is not None:
            self._guardar_recien_nacido(instance, rn_data)

        if postparto_data is not None:
            # El PUT principal del registro nunca reemplaza los controles
            # postparto en bloque; se agregan/corrigen uno por uno a través
            # del endpoint anidado dedicado (ControlPostpartoViewSet).
            pass

        if sangrado_data is not None:
            # Igual que fetocardia/postparto: los controles de sangrado se
            # agregan/corrigen uno por uno vía ControlSangradoViewSet, nunca
            # reemplazando todo el conjunto desde el PUT principal.
            pass
        if globo_data is not None:
            # Igual que sangrado: se agregan/corrigen uno por uno vía
            # ControlGloboViewSet, nunca reemplazando todo el conjunto.
            pass
        if sutura_data is not None:
            # Igual que sangrado: se agregan/corrigen uno por uno vía
            # ControlSuturaViewSet, nunca reemplazando todo el conjunto.
            pass

        return instance


class RegistroPartoListSerializer(serializers.ModelSerializer):
    """Serializer ligero para listados y búsqueda (incluye datos de paciente para autollenado)"""

    class Meta:
        model = RegistroParto
        fields = ['id', 'nombre_paciente', 'identificacion', 'edad_gestacional',
                  'gestas', 'nombre_acompanante', 'tipo_parto', 'nombre_firma_paciente',
                  'created_at']
