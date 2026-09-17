import time

from django.core.management import BaseCommand, call_command


class Command(BaseCommand):
    help = (
        "Ejecuta continuamente la sincronización de frecuencia fetal "
        "desde Dinámica."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--intervalo",
            type=float,
            default=4.0,
            help=(
                "Segundos mínimos entre ciclos. Si el ciclo tarda más, "
                "inicia el siguiente inmediatamente."
            ),
        )
        parser.add_argument(
            "--ciclos",
            type=int,
            default=0,
            help="Cantidad de ciclos de prueba. 0 = ejecución indefinida.",
        )

    def handle(self, *args, **options):
        intervalo = max(0.0, options["intervalo"])
        ciclos = options["ciclos"]
        ejecutados = 0

        self.stdout.write(
            self.style.SUCCESS(
                "[CONTINUO] Iniciando sincronización automática "
                f"de frecuencia fetal (intervalo objetivo: {intervalo:.1f}s)."
            )
        )

        while ciclos == 0 or ejecutados < ciclos:
            inicio = time.monotonic()

            try:
                call_command(
                    "sincronizar_frecuencia_fetal_dinamica",
                    verbosity=1,
                )
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                self.stderr.write(
                    self.style.ERROR(
                        f"[CONTINUO] Error en sincronización fetal: {exc}"
                    )
                )

            ejecutados += 1

            duracion = time.monotonic() - inicio
            espera = max(0.0, intervalo - duracion)

            if ciclos != 0 and ejecutados >= ciclos:
                break

            if espera > 0:
                time.sleep(espera)

        self.stdout.write(
            self.style.SUCCESS(
                "[CONTINUO] Finalizado después de "
                f"{ejecutados} ciclo(s)."
            )
        )
