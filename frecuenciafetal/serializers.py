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


class ControlRecienNacidoSerializer(serializers.ModelSerializer):
    glucometrias = GlucometriaSerializer(many=True, required=False)
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
        control_rn = ControlRecienNacido.objects.create(**validated_data)
        for glucometria_data in glucometrias_data:
            GlucometriaRecienNacido.objects.create(control_rn=control_rn, **glucometria_data)
        return control_rn

    def update(self, instance, validated_data):
        glucometrias_data = validated_data.pop('glucometrias', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        if glucometrias_data is not None:
            instance.glucometrias.all().delete()
            for glucometria_data in glucometrias_data:
                GlucometriaRecienNacido.objects.create(control_rn=instance, **glucometria_data)
        return instance


class ControlPostpartoSerializer(serializers.ModelSerializer):
    class Meta:
        model = ControlPostpartoInmediato
        fields = '__all__'
        read_only_fields = ['registro', 'responsable'] + CAMPOS_FIRMA


class ControlSangradoSerializer(serializers.ModelSerializer):
    class Meta:
        model = ControlSangrado
        fields = '__all__'
        # `estado` (semáforo) se calcula en el backend -- ver
        # `recalcular_estados_sangrado` en models.py -- nunca lo manda el cliente.
        read_only_fields = ['registro', 'estado'] + CAMPOS_FIRMA


class ControlGloboSerializer(serializers.ModelSerializer):
    class Meta:
        model = ControlGlobo
        fields = '__all__'
        read_only_fields = ['registro'] + CAMPOS_FIRMA


class ControlSuturaSerializer(serializers.ModelSerializer):
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
}


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
            rn = ControlRecienNacido.objects.create(registro=registro, **rn_data, **firma)
            for g in glucometrias:
                GlucometriaRecienNacido.objects.create(control_rn=rn, **g)

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

    def update(self, instance, validated_data):
        if instance.completado_en is not None:
            # Registro cerrado -- ver CAMPOS_EDITABLES_POST_CIERRE arriba.
            # No se tocan controles anidados (fetocardia/postparto/
            # sangrado/globo/sutura/recién nacido) desde aquí en este caso.
            for attr, value in validated_data.items():
                if attr in CAMPOS_EDITABLES_POST_CIERRE:
                    setattr(instance, attr, value)
            instance.save()
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
            glucometrias = rn_data.pop('glucometrias', [])
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
            # 2026-09-30: el autoguardado reenvía el recién nacido completo
            # cada vez -- las glucometrías solo se reescriben si cambiaron.
            actuales = [(g.hora, g.resultado) for g in rn.glucometrias.order_by('hora', 'id')]
            nuevas = sorted((g['hora'], g['resultado']) for g in glucometrias)
            if actuales != nuevas:
                rn.glucometrias.all().delete()
                for g in glucometrias:
                    GlucometriaRecienNacido.objects.create(control_rn=rn, **g)

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
