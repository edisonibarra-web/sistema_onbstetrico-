import base64
import hashlib
from django.db import connections
from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.auth.backends import BaseBackend


def _candidatos_clave_dgh(password: str):
    """
    2026-09-09: HALLAZGO — verificado contra datos reales de GENUSUARIO en
    DGEMPRES01, los valores de USUCLAVE (ej. "npoxv68ZzzjW7iyoh33eEQ==") NO
    son MD5 hexadecimal en mayúsculas (lo que comparaba esta función antes,
    ej. "5F4DCC3B..."). Son texto Base64 de exactamente 16 bytes — el
    formato clásico de un MD5 en crudo (no en hexadecimal) codificado en
    Base64. Esto significa que, tal como estaba, este backend NUNCA pudo
    validar una clave real de Dinámica correctamente — el login "funcionaba"
    en las pruebas de este proyecto solo porque AUTHENTICATION_BACKENDS
    también incluye ModelBackend, que valida contra cuentas de Django
    creadas directo para desarrollo, no contra Dinámica.

    ✅ CONFIRMADO 2026-09-09: el usuario hizo una prueba manual de login con
    un usuario y clave reales ya existentes en Dinámica y el ingreso fue
    exitoso — alguna de estas 2 hipótesis (ambas MD5 en crudo, la única
    diferencia es cómo .NET codifica el string a bytes antes de hashear —
    UTF-8 vs UTF-16LE, este último típico de C# clásico con
    Encoding.Unicode/Encoding.Default) es la fórmula correcta que usa
    Dinámica. Se dejan ambas activas a propósito (sin costo real: es una
    comparación adicional, no una consulta extra) en vez de arriesgarse a
    dejar solo una sin poder verificar cuál de las dos fue la que coincidió.
    """
    candidatos = []
    for encoding in ('utf-8', 'utf-16-le'):
        digest = hashlib.md5(password.encode(encoding)).digest()
        candidatos.append(base64.b64encode(digest).decode('ascii'))
    return candidatos


class DGHBackend(BaseBackend):
    """
    Backend de autenticación que valida credenciales contra la base de datos de Dinámica Gerencial (DGH).
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        if not username or not password:
            return None

        # Ver _candidatos_clave_dgh arriba: probamos las hipótesis de hash
        # más plausibles en vez de una sola fórmula fija, dado que el
        # algoritmo real de DGH aún no está confirmado.
        candidatos_clave = _candidatos_clave_dgh(password)

        # 2026-09-09: se cambió el INNER JOIN por LEFT JOIN a propósito. Con
        # INNER JOIN, cualquier usuario de Dinámica que NO fuera médico
        # (enfermeras, personal administrativo, "la jefe", etc.) quedaba
        # excluido del login por completo, aunque su usuario/clave en
        # GENUSUARIO fueran perfectamente válidos — el INNER JOIN descartaba
        # la fila entera si no existía una fila correspondiente en GENMEDICO.
        # Con LEFT JOIN, cualquier usuario ACTIVO de GENUSUARIO puede entrar;
        # los datos de médico (código, tarjeta profesional, tipo) quedan en
        # None cuando no aplican — ya manejado con gracia en otras vistas
        # (ver ControlFetocardiaViewSet.mi_firma en frecuenciafetal/views.py,
        # que devuelve firma_b64: None si no hay codigo_medico en sesión).
        # NUMERODOCUMENTO se agrega como respaldo de identificación para
        # cuando no hay médico/tercero asociado (GENTERCER.TERNUMDOC sigue
        # siendo la fuente preferida cuando sí existe, ver COALESCE abajo).
        sql = """
        SELECT
            GENUSUARIO.USUNOMBRE AS Usuario_DGH,
            GENUSUARIO.USUCLAVE AS Clave_DGH,
            GENUSUARIO.USUDESCRI AS DescripcionU_DGH,
            GENUSUARIO.USUESTADO AS EstadoUSU_DGH,
            GENMEDICO.GMECODIGO AS Codigo_Medico,
            GENMEDICO.GMETARPRO AS TarjetaPRO,
            GENMEDICO.GMETIPMED AS TipoMed_DGH,
            COALESCE(GENTERCER.TERNUMDOC, GENUSUARIO.NUMERODOCUMENTO) AS NumIdeDGH
        FROM GENUSUARIO
        LEFT JOIN GENMEDICO ON GENUSUARIO.USUNOMBRE = GENMEDICO.GMECODIGO
        LEFT JOIN GENTERCER ON GENMEDICO.GENTERCER = GENTERCER.OID
        WHERE GENUSUARIO.USUNOMBRE = %s
          AND GENUSUARIO.USUESTADO = 1 -- Solo usuarios activos
        """

        try:
            with connections['readonly'].cursor() as cursor:
                cursor.execute(sql, [username])
                row = cursor.fetchone()
                
            if row:
                # Mapeo de columnas por índice (basado en el SELECT arriba)
                # usu_nombre, usu_clave, usu_descri, usu_estado, gme_codigo, gme_tarpro, gme_tipmed, ter_numdoc
                db_clave = row[1]

                if db_clave in candidatos_clave:
                    # Usuario válido en DGH.
                    # 3. Sincronizar con el modelo User de Django
                    user_obj, created = User.objects.get_or_create(username=username)
                    if created:
                        user_obj.set_unusable_password()
                    
                    user_obj.first_name = row[2] or ""
                    user_obj.is_staff = False # No es admin de Django por defecto
                    user_obj.save()

                    # 4. Guardar datos adicionales en la sesión del usuario para uso posterior
                    if request:
                        request.session['dgh_info'] = {
                            'codigo_medico': row[4],
                            'tarjeta_pro': row[5],
                            'tipo_med': row[6],
                            'identificacion': row[7],
                            'nombre_completo': row[2]
                        }
                    
                    return user_obj
                    
        except Exception as e:
            print(f"Error en DGH Authentication: {e}")
            return None

        return None

    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None
