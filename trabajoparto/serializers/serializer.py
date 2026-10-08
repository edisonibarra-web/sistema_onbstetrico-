import logging
from decimal import Decimal, InvalidOperation

from rest_framework import serializers
from trabajoparto.models import (
    Aseguradora,
    Paciente,
    Formulario,
    Item,
    Parametro,
    FormularioItemParametro,
    CampoParametro,
    Medicion,
    MedicionValor,
    EstadoFormulario,
    TipoSangre,
    TipoValor,
)
from trabajoparto.utils_aseguradora import get_or_create_aseguradora_by_nombre

logger = logging.getLogger(__name__)


class AseguradoraSerializer(serializers.ModelSerializer):
    """Serializador para el modelo Aseguradora"""
    
    class Meta:
        model = Aseguradora
        fields = ['id', 'nombre']
        read_only_fields = ['id']


class PacienteSerializer(serializers.ModelSerializer):
    """Serializador para el modelo Paciente"""
    tipo_sangre_display = serializers.CharField(source='get_tipo_sangre_display', read_only=True)
    
    class Meta:
        model = Paciente
        fields = [
            'id',
            'num_historia_clinica',
            'num_identificacion',
            'nombres',
            'fecha_nacimiento',
            'tipo_sangre',
            'tipo_sangre_display',
        ]
        read_only_fields = ['id']
        extra_kwargs = {
            'num_historia_clinica': {'required': True},
            'num_identificacion': {'required': True},
            'nombres': {'required': True},
        }


class PacienteListSerializer(serializers.ModelSerializer):
    """Serializador simplificado para listar pacientes"""
    tipo_sangre_display = serializers.CharField(source='get_tipo_sangre_display', read_only=True)
    
    class Meta:
        model = Paciente
        fields = [
            'id', 
            'num_historia_clinica', 
            'num_identificacion', 
            'nombres',
            'tipo_sangre',
            'tipo_sangre_display',
            'fecha_nacimiento',
        ]
        read_only_fields = ['id']


class FormularioSerializer(serializers.ModelSerializer):
    """Serializador para el modelo Formulario con relaciones anidadas"""
    paciente = PacienteListSerializer(read_only=True)
    paciente_id = serializers.PrimaryKeyRelatedField(
        queryset=Paciente.objects.all(),
        source='paciente',
        write_only=True,
        required=True
    )
    aseguradora = AseguradoraSerializer(read_only=True, allow_null=True)
    aseguradora_id = serializers.PrimaryKeyRelatedField(
        queryset=Aseguradora.objects.all(),
        source='aseguradora',
        write_only=True,
        required=False,
        allow_null=True
    )
    estado_display = serializers.CharField(source='get_estado_display', read_only=True)
    
    class Meta:
        model = Formulario
        fields = [
            'id',
            'atencion',
            'codigo',
            'version',
            'fecha_elabora',
            'fecha_actualizacion',
            'num_hoja',
            'paciente',
            'paciente_id',
            'aseguradora',
            'aseguradora_id',
            'diagnostico',
            'edad_snapshot',
            'edad_gestion',
            'estado',
            'estado_display',
            'n_controles_prenatales',
            'gestas',
            'partos',
            'cesareas',
            'abortos',
            'responsable',
        ]
        read_only_fields = ['id', 'fecha_actualizacion']
        extra_kwargs = {
            'codigo': {'required': True},
            'version': {'required': True},
            'fecha_elabora': {'required': True},
            'num_hoja': {'required': True},
            'estado': {'required': True},
            'responsable': {'required': True},
        }


class ItemSerializer(serializers.ModelSerializer):
    """Serializador para el modelo Item"""
    
    class Meta:
        model = Item
        fields = ['id', 'codigo', 'nombre']
        read_only_fields = ['id']
        extra_kwargs = {
            'codigo': {'required': True},
            'nombre': {'required': True},
        }


class ParametroSerializer(serializers.ModelSerializer):
    """Serializador para el modelo Parametro"""
    item = ItemSerializer(read_only=True)
    item_id = serializers.PrimaryKeyRelatedField(
        queryset=Item.objects.all(),
        source='item',
        write_only=True,
        required=True
    )
    
    class Meta:
        model = Parametro
        fields = [
            'id',
            'item',
            'item_id',
            'codigo',
            'nombre',
            'unidad',
            'orden',
            'activo',
        ]
        read_only_fields = ['id']
        extra_kwargs = {
            'codigo': {'required': True},
            'nombre': {'required': True},
        }


class CampoParametroSerializer(serializers.ModelSerializer):
    """Serializador para el modelo CampoParametro"""
    parametro = ParametroSerializer(read_only=True)
    parametro_id = serializers.PrimaryKeyRelatedField(
        queryset=Parametro.objects.all(),
        source='parametro',
        write_only=True,
        required=True
    )
    tipo_valor_display = serializers.CharField(source='get_tipo_valor_display', read_only=True)
    
    class Meta:
        model = CampoParametro
        fields = [
            'id',
            'parametro',
            'parametro_id',
            'codigo',
            'nombre',
            'tipo_valor',
            'tipo_valor_display',
            'unidad',
            'orden',
        ]
        read_only_fields = ['id']
        extra_kwargs = {
            'codigo': {'required': True},
            'nombre': {'required': True},
            'tipo_valor': {'required': True},
        }


class FormularioItemParametroSerializer(serializers.ModelSerializer):
    """Serializador para el modelo FormularioItemParametro"""
    formulario = FormularioSerializer(read_only=True)
    formulario_id = serializers.PrimaryKeyRelatedField(
        queryset=Formulario.objects.all(),
        source='formulario',
        write_only=True,
        required=True
    )
    item = ItemSerializer(read_only=True)
    item_id = serializers.PrimaryKeyRelatedField(
        queryset=Item.objects.all(),
        source='item',
        write_only=True,
        required=True
    )
    parametro = ParametroSerializer(read_only=True)
    parametro_id = serializers.PrimaryKeyRelatedField(
        queryset=Parametro.objects.all(),
        source='parametro',
        write_only=True,
        required=True
    )
    
    class Meta:
        model = FormularioItemParametro
        fields = [
            'id',
            'formulario',
            'formulario_id',
            'item',
            'item_id',
            'parametro',
            'parametro_id',
            'requerido',
        ]
        read_only_fields = ['id']


class MedicionValorSerializer(serializers.ModelSerializer):
    """Serializador para el modelo MedicionValor"""
    campo = CampoParametroSerializer(read_only=True)
    campo_id = serializers.PrimaryKeyRelatedField(
        queryset=CampoParametro.objects.all(),
        source='campo',
        write_only=True,
        required=False,
        allow_null=True
    )
    
    class Meta:
        model = MedicionValor
        fields = [
            'id',
            'campo',
            'campo_id',
            'valor_number',
            'valor_text',
            'valor_boolean',
            'valor_json',
        ]
        read_only_fields = ['id']
        # Desactivamos validadores de unicidad para permitir update_or_create manual
        validators = []
    
    def validate(self, data):
        """Valida que solo un tipo de valor esté presente"""
        valor_number = data.get('valor_number')
        valor_text = data.get('valor_text')
        valor_boolean = data.get('valor_boolean')
        valor_json = data.get('valor_json')
        
        valores_presentes = sum([
            valor_number is not None,
            valor_text is not None,
            valor_boolean is not None,
            valor_json is not None,
        ])
        
        if valores_presentes != 1:
            raise serializers.ValidationError(
                "Debe proporcionarse exactamente un tipo de valor (number, text, boolean o json)."
            )
        
        return data


class MedicionSerializer(serializers.ModelSerializer):
    """Serializador para el modelo Medicion con valores anidados"""
    formulario = FormularioSerializer(read_only=True)
    formulario_id = serializers.PrimaryKeyRelatedField(
        queryset=Formulario.objects.all(),
        source='formulario',
        write_only=True,
        required=True
    )
    parametro = ParametroSerializer(read_only=True)
    parametro_id = serializers.PrimaryKeyRelatedField(
        queryset=Parametro.objects.all(),
        source='parametro',
        write_only=True,
        required=True
    )
    valores = MedicionValorSerializer(many=True, read_only=True)
    
    class Meta:
        model = Medicion
        fields = [
            'id',
            'formulario',
            'formulario_id',
            'parametro',
            'parametro_id',
            'tomada_en',
            'observacion',
            'responsable',
            'valores',
        ]
        read_only_fields = ['id']
        extra_kwargs = {
            'tomada_en': {'required': True},
        }


# Serializadores para crear/actualizar con relaciones simplificadas
class FormularioCreateSerializer(serializers.ModelSerializer):
    """Serializador simplificado para crear Formularios. Acepta aseguradora (id) o aseguradora_nombre (texto)."""

    aseguradora_nombre = serializers.CharField(write_only=True, required=False, allow_blank=True)

    class Meta:
        model = Formulario
        fields = [
            'id',
            'atencion',
            'codigo',
            'version',
            'fecha_elabora',
            'num_hoja',
            'paciente',
            'aseguradora',
            'aseguradora_nombre',
            'diagnostico',
            'edad_snapshot',
            'edad_gestion',
            'estado',
            'n_controles_prenatales',
            # 2026-09-23: G/P/C/A faltaban aquí -- este serializer es el que usan
            # create/update (FormularioViewSet.get_serializer_class), así que lo
            # que se digitaba en esos campos se descartaba en silencio y nunca
            # quedaba guardado.
            'gestas',
            'partos',
            'cesareas',
            'abortos',
            'responsable',
        ]
        read_only_fields = ['id']
        extra_kwargs = {
            'codigo': {'required': True},
            'version': {'required': True},
            'fecha_elabora': {'required': True},
            'num_hoja': {'required': True},
            'paciente': {'required': True},
            'estado': {'required': True},
            'responsable': {'required': True},
            'aseguradora': {'required': False},
        }

    def validate(self, attrs):
        nom = attrs.pop('aseguradora_nombre', None)
        if nom is not None and isinstance(nom, str):
            n = nom.strip()
            if n:
                ase, _ = get_or_create_aseguradora_by_nombre(n)
                attrs['aseguradora'] = ase
            else:
                attrs['aseguradora'] = None
        return attrs


_CAMPOS_VALOR = ('valor_number', 'valor_text', 'valor_boolean', 'valor_json')


def _mismo_valor(existente, valor_data):
    """True si el valor enviado es igual al ya guardado (Decimal vs float incluido)."""
    for nombre in _CAMPOS_VALOR:
        actual, nuevo = getattr(existente, nombre), valor_data.get(nombre)
        if actual is None and nuevo is None:
            continue
        if actual is None or nuevo is None:
            return False
        if nombre == 'valor_number':
            try:
                if Decimal(str(actual)) != Decimal(str(nuevo)):
                    return False
            except (InvalidOperation, ValueError):
                return False
        elif nombre == 'valor_text':
            if str(actual).strip() != str(nuevo).strip():
                return False
        elif actual != nuevo:
            return False
    return True


class MedicionCreateSerializer(serializers.ModelSerializer):
    """Serializador para crear Mediciones con valores anidados"""
    valores = MedicionValorSerializer(many=True, required=False)
    
    class Meta:
        model = Medicion
        fields = [
            'id',
            'formulario',
            'parametro',
            'tomada_en',
            'observacion',
            'responsable',
            'valores',
        ]
        # Eliminamos validadores automáticos de unicidad para manejarlo
        # manualmente en el método create con get_or_create
        validators = []

    def create(self, validated_data):
        valores_data = validated_data.pop('valores', [])
        # Manejar si ya existe la medición para el mismo formulario, parámetro y hora
        formulario = validated_data.get('formulario')
        parametro = validated_data.get('parametro')
        tomada_en = validated_data.get('tomada_en')

        medicion, created = Medicion.objects.get_or_create(
            formulario=formulario,
            parametro=parametro,
            tomada_en=tomada_en,
            defaults=validated_data
        )

        # 2026-10-08: un control ya registrado NO se reescribe con cada guardado.
        # Antes, cada autoguardado reenviaba los controles cargados en pantalla
        # con el nombre de quien estaba conectada: el responsable original se
        # reemplazaba (los controles de una enfermera quedaban a nombre de la
        # del turno siguiente) y sus valores podían quedar pisados sin rastro.
        # Ahora:
        # - responsable: se conserva el de quien registró el control; solo se
        #   completa si estaba vacío.
        # - valores: un valor ya guardado solo cambia si el frontend lo envía
        #   como corrección explícita ("corregir": true, tras confirmar la
        #   enfermera). Los campos que el control aún no tenía sí se agregan.
        corregir = str(self.initial_data.get('corregir', '')).lower() in ('true', '1')
        if not created:
            campos_actualizables = []
            if validated_data.get('observacion') and validated_data['observacion'] != medicion.observacion:
                medicion.observacion = validated_data['observacion']
                campos_actualizables.append('observacion')
            if validated_data.get('responsable') and not (medicion.responsable or '').strip():
                medicion.responsable = validated_data['responsable']
                campos_actualizables.append('responsable')
            if campos_actualizables:
                medicion.save(update_fields=campos_actualizables)

        existentes = {v.campo_id: v for v in medicion.valores.all()} if not created else {}
        for valor_data in valores_data:
            campo = valor_data.get('campo')
            if not campo:
                continue
            existente = existentes.get(campo.id)
            if existente is None:
                MedicionValor.objects.create(medicion=medicion, **valor_data)
            elif _mismo_valor(existente, valor_data):
                continue
            elif corregir:
                for nombre in _CAMPOS_VALOR:
                    setattr(existente, nombre, valor_data.get(nombre))
                existente.save()
            else:
                logger.warning(
                    'Medición %s (formulario %s, %s): se ignoró un cambio no confirmado del campo %s',
                    medicion.id, formulario.id if formulario else None, tomada_en, campo.id,
                )

        return medicion


class PacienteCompletoSerializer(serializers.Serializer):
    """
    Serializador consolidado para obtener toda la información de un paciente
    incluyendo sus formularios y mediciones en una sola respuesta
    """
    paciente = PacienteSerializer()
    formulario = FormularioSerializer(allow_null=True, required=False)
    mediciones = MedicionSerializer(many=True, required=False, allow_null=True)
    
    class Meta:
        fields = ['paciente', 'formulario', 'mediciones']

