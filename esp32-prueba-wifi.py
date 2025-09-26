import network
import machine
import time

# Configuración WiFi
SSID = "motog35"        # Cambia por tu red WiFi
PASSWORD = "12345678"   # Cambia por tu contraseña

# Configurar pines de LEDs
led1 = machine.Pin(2, machine.Pin.OUT)   # Verde 1
led2 = machine.Pin(4, machine.Pin.OUT)   # Verde 2
led3 = machine.Pin(5, machine.Pin.OUT)   # Verde 3
led4 = machine.Pin(18, machine.Pin.OUT)  # Amarillo 4
led5 = machine.Pin(19, machine.Pin.OUT)  # Rojo 5
led6 = machine.Pin(21, machine.Pin.OUT)  # Rojo 6

# Lista de LEDs para fácil manejo
leds = [led1, led2, led3, led4, led5, led6]

def apagar_todos_leds():
    """Apaga todos los LEDs"""
    for led in leds:
        led.off()

def encender_leds(cantidad):
    """Enciende la cantidad especificada de LEDs"""
    apagar_todos_leds()
    for i in range(min(cantidad, len(leds))):
        leds[i].on()

def calcular_leds_por_rssi(rssi):
    """Calcula cuántos LEDs encender según el RSSI"""
    if rssi >= -50:
        return 6  # Excelente
    elif rssi >= -60:
        return 5  # Buena
    elif rssi >= -70:
        return 4  # Aceptable
    elif rssi >= -80:
        return 3  # Débil
    elif rssi >= -90:
        return 2  # Muy débil
    else:
        return 1  # Prácticamente inutilizable

def obtener_clasificacion(rssi):
    """Obtiene la clasificación textual de la señal"""
    if rssi >= -50:
        return "Excelente"
    elif rssi >= -60:
        return "Buena"
    elif rssi >= -70:
        return "Aceptable"
    elif rssi >= -80:
        return "Débil"
    elif rssi >= -90:
        return "Muy débil"
    else:
        return "Prácticamente inutilizable"

def crear_barras_visuales(leds_encendidos):
    """Crea representación visual con caracteres"""
    barras = ""
    for i in range(6):
        if i < leds_encendidos:
            barras += "█"
        else:
            barras += "░"
    return barras

def conectar_wifi():
    """Conecta a la red WiFi con manejo robusto de errores"""
    try:
        # Desactivar WiFi primero (limpia estado)
        wlan = network.WLAN(network.STA_IF)
        wlan.active(False)
        time.sleep(1)

        # Activar WiFi
        wlan.active(True)
        time.sleep(2)

        # Verificar si ya está conectado
        if wlan.isconnected():
            print("Ya conectado a WiFi")
            print(f"IP: {wlan.ifconfig()[0]}")
            return wlan

        print("Conectando a WiFi...")
        print(f"Red: {SSID}")

        # Conectar con reintentos
        for intento in range(3):
            try:
                wlan.connect(SSID, PASSWORD)

                # Esperar conexión
                contador = 0
                while not wlan.isconnected() and contador < 20:
                    print(".", end="")
                    time.sleep(0.5)
                    contador += 1

                print()  # Nueva línea

                if wlan.isconnected():
                    print("WiFi conectado!")
                    print(f"IP: {wlan.ifconfig()[0]}")
                    print(f"Gateway: {wlan.ifconfig()[2]}")
                    return wlan
                else:
                    print(f"Intento {intento + 1} falló")
                    if intento < 2:
                        time.sleep(2)

            except Exception as e:
                print(f"Error en intento {intento + 1}: {e}")
                time.sleep(2)

        print("Error: No se pudo conectar a WiFi después de 3 intentos")
        return None

    except Exception as e:
        print(f"Error crítico de WiFi: {e}")
        return None

def main():
    """Función principal"""
    print("=== Indicador de Señal WiFi con LEDs ===")

    # Apagar todos los LEDs al inicio
    apagar_todos_leds()

    # Pequeña pausa para estabilizar
    time.sleep(2)

    # Conectar a WiFi
    wlan = conectar_wifi()

    if wlan is None:
        print("Sin conexión WiFi - Mostrando error con LEDs")
        # Parpadear LED 1 para indicar error
        for i in range(6):
            led1.on()
            time.sleep(0.3)
            led1.off()
            time.sleep(0.3)
        return

    print("Iniciando monitoreo de señal...")
    print("Presiona Ctrl+C para detener")

    try:
        while True:
            try:
                if wlan.isconnected():
                    # Obtener RSSI (intensidad de señal)
                    rssi = wlan.status('rssi')

                    # Calcular LEDs a encender
                    leds_encendidos = calcular_leds_por_rssi(rssi)

                    # Encender LEDs correspondientes
                    encender_leds(leds_encendidos)

                    # Mostrar información en consola
                    clasificacion = obtener_clasificacion(rssi)
                    barras = crear_barras_visuales(leds_encendidos)

                    print(f"RSSI: {rssi} dBm - {clasificacion} [{barras}] {leds_encendidos}/6 LEDs")

                else:
                    print("WiFi desconectado - Reintentando...")
                    apagar_todos_leds()
                    time.sleep(1)
                    wlan = conectar_wifi()

            except Exception as e:
                print(f"Error en bucle principal: {e}")
                time.sleep(2)
                continue

            time.sleep(2)  # Actualizar cada 2 segundos

    except KeyboardInterrupt:
        print("\nDeteniendo programa...")
        apagar_todos_leds()
        print("LEDs apagados - Programa terminado")
    except Exception as e:
        print(f"Error crítico: {e}")
        apagar_todos_leds()

# Ejecutar programa principal
if __name__ == "__main__":
    main()
