import hashlib
from django.db import connections
from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.auth.backends import BaseBackend

class DGHBackend(BaseBackend):
    """
    Backend de autenticación que valida credenciales contra la base de datos de Dinámica Gerencial (DGH).
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        if not username or not password:
            return None

        # 1. Encriptar el password ingresado (DGH suele usar MD5 o similar)
        # Nota: Ajustar este hash si el algoritmo de DGH es diferente.
        password_enc = hashlib.md5(password.encode('utf-8')).hexdigest().upper()

        sql = """
        SELECT 
            GENUSUARIO.USUNOMBRE AS Usuario_DGH,
            GENUSUARIO.USUCLAVE AS Clave_DGH,
            GENUSUARIO.USUDESCRI AS DescripcionU_DGH,
            GENUSUARIO.USUESTADO AS EstadoUSU_DGH,
            GENMEDICO.GMECODIGO AS Codigo_Medico,
            GENMEDICO.GMETARPRO AS TarjetaPRO,
            GENMEDICO.GMETIPMED AS TipoMed_DGH,
            GENTERCER.TERNUMDOC AS NumIdeDGH
        FROM GENUSUARIO
        INNER JOIN GENMEDICO ON GENUSUARIO.USUNOMBRE = GENMEDICO.GMECODIGO
        INNER JOIN GENTERCER ON GENMEDICO.GENTERCER = GENTERCER.OID
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
                
                # 2. Comparación de claves (Ajustar si DGH usa otro método)
                if db_clave == password_enc:
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
