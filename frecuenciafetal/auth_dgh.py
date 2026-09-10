import base64
import hashlib
import logging
from django.db import connections
from django.conf import settings
from django.contrib.auth.models import User, Group
from django.contrib.auth.backends import BaseBackend

# 2026-09-10: logging en vez de print() sueltos. Este logger cuelga de
# 'frecuenciafetal' (ver LOGGING en settings.py) y sale a consola/stdout.
# REGLA: nunca registrar la contraseña, el hash de Dinámica (USUCLAVE) ni
# ningún candidato de _candidatos_clave_dgh.
logger = logging.getLogger('frecuenciafetal.auth')


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
                    elif user_obj.has_usable_password():
                        # 🔒 HALLAZGO DE SEGURIDAD 2026-09-09 — "secuestro de identidad":
                        # esta cuenta de Django YA existía con una contraseña local
                        # utilizable, es decir, alguien la creó antes desde /registro/
                        # (ver registro_usuario_view en views.py) usando este mismo
                        # username. Como ese username ACABA de validarse con éxito
                        # contra Dinámica, dos escenarios son posibles: (a) la misma
                        # persona se registró localmente antes de tener cuenta en
                        # Dinámica y ahora ya la tiene (caso normal, sin problema), o
                        # (b) alguien más "reservó" este username localmente ANTES de
                        # que su dueño real tuviera cuenta en Dinámica, y sin este
                        # bloque conservaría acceso paralelo indefinido a la cuenta con
                        # su clave local, aunque el dueño legítimo ya esté usando su
                        # clave real de Dinámica (la clave local nunca se invalidaba).
                        # No podemos distinguir (a) de (b) aquí, así que se invalida la
                        # clave local en ambos casos: a partir de ahora este username
                        # SOLO puede entrar por Dinámica, cerrando la ventana de acceso
                        # paralelo. Se marca con un grupo para que Sistemas pueda
                        # auditar cuándo pasó (y revisar si fue el caso (b)).
                        user_obj.set_unusable_password()
                        grupo_reclamo, _ = Group.objects.get_or_create(
                            name='Cuenta local reclamada por Dinámica (revisar)'
                        )
                        user_obj.groups.add(grupo_reclamo)
                        logger.warning(
                            "Contraseña local invalidada para el usuario '%s': se "
                            "confirmó como usuario válido de Dinámica Gerencial. "
                            "Revisar en /admin/ si el registro local previo fue legítimo.",
                            username,
                        )

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
                    
        except Exception:
            # 2026-09-09: hallazgo "dependencia de disponibilidad de Dinámica"
            # -- si Dinámica no responde (o cualquier otro error de conexión/
            # consulta), esto NO significa que la contraseña esté mal, sino
            # que no se pudo verificar. Se marca en el propio request para que
            # login_view pueda mostrar un mensaje distinto y más útil ("no se
            # pudo validar, intente de nuevo o use su cuenta local de
            # respaldo") en vez del genérico "usuario o contraseña
            # incorrectos", que sería engañoso en este caso.
            # logger.exception incluye el traceback en el LOG (no en la
            # respuesta al usuario). No se registra el username en el mensaje
            # para no dejar en el log intentos de nombres inexistentes.
            logger.exception("Error al validar credenciales contra Dinámica Gerencial")
            if request is not None:
                request.dgh_connection_error = True
            return None

        return None

    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None
