from rest_framework import serializers
from .models import (
    RegistroParto, ControlFetocardia, ControlRecienNacido,
    GlucometriaRecienNacido, ControlPostpartoInmediato, FirmaPaciente, Huella
)


def _get_firma_url_and_cleanup(registro):
    """
    Devuelve la URL de firma solo si el archivo existe.
    Si el registro apunta a un archivo inexistente, limpia el campo en BD.
    """
    firma = getattr(registro, 'firma_paciente', None)
    if not firma:
        return None
    try:
        if not firma.name:
            return None
        if firma.storage.exists(firma.name):
            return firma.url
    except Exception:
        return None

    # Si llegamos aqui, hay referencia huerfana a archivo faltante.
    try:
        registro.firma_paciente = None
        registro.save(update_fields=['firma_paciente', 'updated_at'])
    except Exception:
        # Si falla la limpieza, evitar romper la respuesta API.
        pass
    return None


class ControlFetocardiaSerializer(serializers.ModelSerializer):
    class Meta:
        model = ControlFetocardia
        fields = '__all__'
        read_only_fields = ['registro']


class GlucometriaSerializer(serializers.ModelSerializer):
    class Meta:
        model = GlucometriaRecienNacido
        fields = '__all__'
        read_only_fields = ['control_rn']


class ControlRecienNacidoSerializer(serializers.ModelSerializer):
    glucometrias = GlucometriaSerializer(many=True, required=False)

    class Meta:
        model = ControlRecienNacido
        fields = '__all__'
        read_only_fields = ['registro']

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
        read_only_fields = ['registro']


class RegistroPartoSerializer(serializers.ModelSerializer):
    controles_fetocardia = ControlFetocardiaSerializer(many=True, required=False)
    control_recien_nacido = ControlRecienNacidoSerializer(required=False)
    controles_postparto = ControlPostpartoSerializer(many=True, required=False)
    huella_biometrica = serializers.SerializerMethodField()
    firma_paciente = serializers.SerializerMethodField()

    class Meta:
        model = RegistroParto
        fields = '__all__'

    def create(self, validated_data):
        fetocardia_data = validated_data.pop('controles_fetocardia', []) or []
        rn_data = validated_data.pop('control_recien_nacido', None)
        postparto_data = validated_data.pop('controles_postparto', []) or []

        registro = RegistroParto.objects.create(**validated_data)

        for fc in fetocardia_data:
            fc_dict = dict(fc) if hasattr(fc, 'items') else fc
            fc_clean = {
                'fecha': fc_dict.get('fecha'),
                'hora': fc_dict.get('hora'),
                'fetocardia': fc_dict.get('fetocardia'),
                'responsable': fc_dict.get('responsable', '') or '',
            }
            if fc_clean['fecha'] is not None and fc_clean['hora'] is not None and fc_clean['fetocardia'] is not None:
                ControlFetocardia.objects.create(registro=registro, **fc_clean)

        if rn_data:
            glucometrias = rn_data.pop('glucometrias', [])
            rn = ControlRecienNacido.objects.create(registro=registro, **rn_data)
            for g in glucometrias:
                GlucometriaRecienNacido.objects.create(control_rn=rn, **g)

        for cp in postparto_data:
            ControlPostpartoInmediato.objects.create(registro=registro, **cp)

        return registro

    def get_huella_biometrica(self, obj):
        id_numerica = obj.identificacion.replace('.', '').replace('-', '')
        
        # 1. FirmaPaciente vinculada
        huella = FirmaPaciente.objects.filter(formulario=obj).order_by('-fecha').first()
        if not huella:
            # 2. FirmaPaciente por ID
            huella = FirmaPaciente.objects.filter(paciente_id=id_numerica).order_by('-fecha').first()
            
        if huella and huella.imagen_huella:
            return huella.imagen_huella.url
            
        # 3. Modelo Huella (Android)
        huella_raw = Huella.objects.filter(documento=obj.identificacion).order_by('-fecha').first()
        if not huella_raw:
            huella_raw = Huella.objects.filter(documento=id_numerica).order_by('-fecha').first()
            
        if huella_raw and huella_raw.imagen_huella:
            return huella_raw.imagen_huella.url
            
        return None

    def get_firma_paciente(self, obj):
        return _get_firma_url_and_cleanup(obj)

    def update(self, instance, validated_data):
        fetocardia_data = validated_data.pop('controles_fetocardia', None)
        rn_data = validated_data.pop('control_recien_nacido', None)
        postparto_data = validated_data.pop('controles_postparto', None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if fetocardia_data is not None:
            # No modificar fetocardia en update: una vez guardados no se editan (solo se pueden agregar nuevos)
            pass
        if rn_data is not None:
            glucometrias = rn_data.pop('glucometrias', [])
            rn, _ = ControlRecienNacido.objects.update_or_create(
                registro=instance, defaults=rn_data
            )
            rn.glucometrias.all().delete()
            for g in glucometrias:
                GlucometriaRecienNacido.objects.create(control_rn=rn, **g)

        if postparto_data is not None:
            # No modificar postparto en update: una vez guardados no se editan (solo se pueden agregar nuevos)
            pass

        return instance


class RegistroPartoListSerializer(serializers.ModelSerializer):
    """Serializer ligero para listados y búsqueda (incluye datos de paciente para autollenado)"""
    firma_paciente = serializers.SerializerMethodField()

    class Meta:
        model = RegistroParto
        fields = ['id', 'nombre_paciente', 'identificacion', 'edad_gestacional',
                  'gestas', 'nombre_acompanante', 'tipo_parto', 'nombre_firma_paciente', 
                  'firma_paciente', 'created_at']

    def get_firma_paciente(self, obj):
        return _get_firma_url_and_cleanup(obj)


class FirmaPacienteSerializer(serializers.ModelSerializer):
    class Meta:
        model = FirmaPaciente
        fields = '__all__'
