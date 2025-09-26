import network
import machine
import time
import dht
import onewire
import ds18x20

# Configuración WiFi
SSID = "motog35"
PASSWORD = "12345678"

# Configuración de pines
DHT22_PIN = 4
DS18B20_PIN = 5
WIFI_LED_PIN = 2

# Inicializar sensores
dht22 = dht.DHT22(machine.Pin(DHT22_PIN))
ds_pin = machine.Pin(DS18B20_PIN)
ds_sensor = ds18x20.DS18X20(onewire.OneWire(ds_pin))

# Inicializar LED WiFi
wifi_led = machine.Pin(WIFI_LED_PIN, machine.Pin.OUT)
wifi_led.off()

# Variables de control de tiempo (en milisegundos)
def get_time_ms():
    return time.ticks_ms()

# Intervalos en milisegundos
SENSOR_INTERVAL = 2000      # Leer sensores cada 2 segundos
WIFI_CHECK_INTERVAL = 10000 # Verificar WiFi cada 10 segundos
LED_BLINK_INTERVAL = 500    # Parpadeo LED cada 500ms

# Variables de tiempo
last_sensor_read = 0
last_wifi_check = 0
last_led_blink = 0

# Estado del sistema
wifi_connected = False
wifi_reconnecting = False
led_state = False
wifi_retry_count = 0

# Datos de sensores
class SensorData:
    def __init__(self):
        self.dht_temp = None
        self.dht_humidity = None
        self.ds18b20_temp = None
        self.dht_valid = False
        self.ds18b20_valid = False
        self.timestamp = 0

current_data = SensorData()

# Encontrar dispositivos DS18B20
ds_devices = []

def initialize_sensors():
    """Inicializa todos los sensores"""
    global ds_devices

    print("Inicializando sensores...")

    # Inicializar DHT22
    print("- DHT22 en pin", DHT22_PIN)

    # Buscar sensores DS18B20
    print("- Buscando sensores DS18B20...")
    ds_devices = ds_sensor.scan()
    if ds_devices:
        print(f"  ✓ Encontrados {len(ds_devices)} sensor(es) DS18B20")
        for i, device in enumerate(ds_devices):
            print(f"    Sensor {i}: {device.hex()}")
    else:
        print("  ⚠ No se encontraron sensores DS18B20")

    print("Sensores inicializados\n")

def initialize_wifi():
    """Inicializa WiFi en modo no-bloqueante"""
    global wlan

    print("Configurando WiFi...")
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)

    if not wlan.isconnected():
        print(f"Conectando a: {SSID}")
        wlan.connect(SSID, PASSWORD)

    print("WiFi iniciado en modo no-bloqueante\n")
    return wlan

def read_sensors_event():
    """Evento: Leer todos los sensores"""
    global current_data

    current_data.timestamp = get_time_ms() // 1000

    # Leer DHT22
    try:
        dht22.measure()
        current_data.dht_temp = dht22.temperature()
        current_data.dht_humidity = dht22.humidity()
        current_data.dht_valid = True
    except Exception as e:
        current_data.dht_valid = False
        # print(f"Error DHT22: {e}")

    # Leer DS18B20
    if ds_devices:
        try:
            ds_sensor.convert_temp()
            time.sleep_ms(750)  # Esperar conversión
            temp = ds_sensor.read_temp(ds_devices[0])
            if temp is not None:
                current_data.ds18b20_temp = temp
                current_data.ds18b20_valid = True
            else:
                current_data.ds18b20_valid = False
        except Exception as e:
            current_data.ds18b20_valid = False
            # print(f"Error DS18B20: {e}")
    else:
        current_data.ds18b20_valid = False

def check_wifi_event():
    """Evento: Verificar estado WiFi y manejar reconexión"""
    global wifi_connected, wifi_reconnecting, wifi_retry_count

    if wlan.isconnected():
        if not wifi_connected:
            print("\n🌐 WiFi CONECTADO!")
            print(f"   IP: {wlan.ifconfig()[0]}")
            print(f"   RSSI: {wlan.status('rssi')} dBm")
            wifi_connected = True
            wifi_reconnecting = False
            wifi_retry_count = 0
    else:
        if wifi_connected:
            print("\n⚠ WiFi DESCONECTADO")
            wifi_connected = False
            wifi_reconnecting = True

        wifi_retry_count += 1
        if wifi_retry_count >= 3:  # Reintentar cada 30 segundos (3 * 10s)
            print("🔄 Reintentando conexión WiFi...")
            try:
                wlan.connect(SSID, PASSWORD)
            except:
                pass
            wifi_retry_count = 0
        elif wifi_retry_count == 1:
            wifi_reconnecting = True

def update_wifi_led():
    """Evento: Actualizar estado del LED WiFi"""
    global led_state, last_led_blink

    current_time = get_time_ms()

    if wifi_connected:
        # WiFi conectado: LED siempre encendido
        wifi_led.on()

    elif wifi_reconnecting:
        # WiFi reconectando: LED parpadeando cada 500ms
        if time.ticks_diff(current_time, last_led_blink) >= LED_BLINK_INTERVAL:
            led_state = not led_state
            if led_state:
                wifi_led.on()
            else:
                wifi_led.off()
            last_led_blink = current_time
    else:
        # WiFi desconectado: LED apagado
        wifi_led.off()

def display_sensor_data():
    """Mostrar datos de sensores en consola"""
    timestamp_str = f"[{current_data.timestamp:06d}]"

    # Mostrar DHT22
    if current_data.dht_valid:
        dht_str = f"DHT22: {current_data.dht_temp:.1f}°C, {current_data.dht_humidity:.1f}%"
    else:
        dht_str = "DHT22: ERROR"

    # Mostrar DS18B20
    if current_data.ds18b20_valid:
        ds_str = f"DS18B20: {current_data.ds18b20_temp:.2f}°C"
    else:
        ds_str = "DS18B20: ERROR"

    # Mostrar estado WiFi con manejo seguro de RSSI
    try:
        if wifi_connected and wlan.isconnected():
            rssi = wlan.status('rssi')
            wifi_str = f"WiFi: ✓ CONECTADO ({rssi} dBm) [LED: ON]"
        elif wifi_reconnecting:
            wifi_str = "WiFi: 🔄 RECONECTANDO [LED: BLINK]"
        else:
            wifi_str = "WiFi: ✗ DESCONECTADO [LED: OFF]"
    except Exception:
        # Si hay error al obtener RSSI, asumir desconectado
        wifi_str = "WiFi: ✗ DESCONECTADO [LED: OFF]"

    print(f"{timestamp_str} {dht_str} | {ds_str} | {wifi_str}")

def main():
    """Función principal con arquitectura de eventos"""
    global last_sensor_read, last_wifi_check

    print("=== ESP32 Monitor de Sensores + WiFi ===")
    print("DHT22 + DS18B20 - Arquitectura basada en eventos")
    print("MicroPython - Un solo núcleo\n")

    # Inicializar componentes
    initialize_sensors()
    wlan = initialize_wifi()

    print("Sistema iniciado - Usando eventos en núcleo principal")
    print("Formato: [Tiempo] DHT22: XX°C, XX% | DS18B20: XX°C | WiFi: Estado")
    print("Presiona Ctrl+C para detener\n")

    # Inicializar tiempos
    start_time = get_time_ms()
    last_sensor_read = start_time
    last_wifi_check = start_time

    try:
        while True:
            current_time = get_time_ms()

            # EVENTO 1: Leer sensores cada SENSOR_INTERVAL
            if time.ticks_diff(current_time, last_sensor_read) >= SENSOR_INTERVAL:
                read_sensors_event()
                display_sensor_data()
                last_sensor_read = current_time

            # EVENTO 2: Verificar WiFi cada WIFI_CHECK_INTERVAL
            if time.ticks_diff(current_time, last_wifi_check) >= WIFI_CHECK_INTERVAL:
                check_wifi_event()
                last_wifi_check = current_time

            # EVENTO 3: Actualizar LED WiFi (continuo)
            update_wifi_led()

            # Pequeña pausa para no saturar el procesador
            time.sleep_ms(10)

    except KeyboardInterrupt:
        print("\n\nDeteniendo programa...")
        wifi_led.off()
        print("LED apagado - Programa terminado")

    except Exception as e:
        print(f"\nError crítico: {e}")
        wifi_led.off()

# Funciones auxiliares para expansiones futuras
def get_current_sensor_data():
    """Obtener datos actuales de sensores"""
    return current_data

def is_wifi_connected():
    """Verificar si WiFi está conectado"""
    return wifi_connected

# Ejecutar programa principal
if __name__ == "__main__":
    main()
