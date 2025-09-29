import network
import machine
import time
import dht
import onewire
import ds18x20
from machine import Pin, SoftI2C

# Intentar importar ssd1306
try:
    import ssd1306
    OLED_AVAILABLE = True
    print("✓ Librería ssd1306 encontrada")
except ImportError:
    OLED_AVAILABLE = False
    print("⚠ Librería ssd1306 no encontrada - OLED deshabilitado")

# Configuración WiFi
SSID = "motog35"
PASSWORD = "12345678"

# Configuración de pines
DHT22_PIN = 4
DS18B20_PIN = 5
WIFI_LED_PIN = 2

# Configuración OLED
OLED_SCL_PIN = 22
OLED_SDA_PIN = 21
OLED_WIDTH = 128
OLED_HEIGHT = 64

# Configuración de zona horaria (Perú UTC-5)
TIMEZONE_OFFSET = -5 * 3600  # -5 horas en segundos

# Estado de sincronización de tiempo
time_synced = False
last_ntp_sync = 0
NTP_SYNC_INTERVAL = 3600000  # Sincronizar cada hora (1 hora = 3600000 ms)

# Variables de control de tiempo
def get_time_ms():
    return time.ticks_ms()

# Intervalos en milisegundos
SENSOR_INTERVAL = 2000
WIFI_CHECK_INTERVAL = 10000
LED_BLINK_INTERVAL = 500
OLED_UPDATE_INTERVAL = 1000

# Variables de tiempo
last_sensor_read = 0
last_wifi_check = 0
last_led_blink = 0
last_oled_update = 0

# Estado del sistema
wifi_connected = False
wifi_reconnecting = False
led_state = False
wifi_retry_count = 0

# Funciones para barras WiFi
def get_wifi_signal_bars(rssi):
    """Convierte RSSI (dBm) a número de barras de señal (0-6)"""
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
        return 1  # Inutilizable

def obtener_clasificacion_wifi(rssi):
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
        return "Inutilizable"

def crear_barras_wifi(barras_activas):
    """Crea representación visual con caracteres ASCII"""
    barras = ""
    for i in range(6):
        if i < barras_activas:
            barras += "X"  # Barra llena
        else:
            barras += "O"  # Barra vacía
    return barras

# Inicializar I2C y OLED solo si está disponible
oled_initialized = False
if OLED_AVAILABLE:
    try:
        i2c = SoftI2C(scl=Pin(OLED_SCL_PIN), sda=Pin(OLED_SDA_PIN))
        oled = ssd1306.SSD1306_I2C(OLED_WIDTH, OLED_HEIGHT, i2c)
        oled_initialized = True
        print("✓ OLED inicializado correctamente")
    except Exception as e:
        oled_initialized = False
        print(f"⚠ Error inicializando OLED: {e}")

# Inicializar sensores
dht22 = dht.DHT22(machine.Pin(DHT22_PIN))
ds_pin = machine.Pin(DS18B20_PIN)
ds_sensor = ds18x20.DS18X20(onewire.OneWire(ds_pin))

# Inicializar LED WiFi
wifi_led = machine.Pin(WIFI_LED_PIN, machine.Pin.OUT)
wifi_led.off()

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
ds_devices = []

def sync_time_from_ntp():
    """Sincroniza tiempo con servidor NTP"""
    global time_synced, last_ntp_sync

    if not wifi_connected:
        return False

    try:
        print("🕐 Sincronizando tiempo con NTP...")

        # Importar y usar ntptime
        import ntptime

        # Sincronizar tiempo
        ntptime.settime()

        # Marcar como sincronizado
        time_synced = True
        last_ntp_sync = get_time_ms()

        # Mostrar tiempo sincronizado
        current_time = time.localtime()
        print(f"✓ Tiempo sincronizado: {current_time[2]:02d}/{current_time[1]:02d}/{current_time[0]} {current_time[3]:02d}:{current_time[4]:02d}:{current_time[5]:02d}")

        return True

    except Exception as e:
        print(f"⚠ Error sincronizando NTP: {e}")
        time_synced = False
        return False

def get_local_time():
    """Obtiene tiempo local ajustado a zona horaria"""
    try:
        # Obtener tiempo UTC del sistema
        utc_time = time.time()

        # Ajustar a zona horaria local (Perú UTC-5)
        local_timestamp = utc_time + TIMEZONE_OFFSET

        # Convertir a tupla de tiempo local
        local_time = time.localtime(local_timestamp)

        return local_time
    except:
        # Si hay error, devolver tiempo de fallback
        return (2025, 9, 28, 12, 0, 0, 0, 0)

def get_formatted_datetime():
    """Obtiene fecha y hora formateada desde RTC real"""
    if time_synced:
        try:
            local_time = get_local_time()

            # Formatear fecha: dd/mm/yy
            date_str = f"{local_time[2]:02d}/{local_time[1]:02d}/{local_time[0]%100:02d}"

            # Formatear hora: hh:mm
            time_str = f"{local_time[3]:02d}:{local_time[4]:02d}"

            return date_str, time_str
        except:
            pass

    # Fallback si no hay tiempo sincronizado
    return "01/01/25", "00:00"

def check_ntp_sync():
    """Verifica si es momento de sincronizar NTP"""
    global last_ntp_sync

    current_time = get_time_ms()

    # Sincronizar al conectar WiFi o cada hora
    if wifi_connected and (not time_synced or
                          time.ticks_diff(current_time, last_ntp_sync) >= NTP_SYNC_INTERVAL):
        sync_time_from_ntp()

def initialize_oled():
    """Inicializa el display OLED"""
    if not oled_initialized:
        return False

    try:
        oled.fill(0)
        oled.text_small("Iniciando...", 0, 0, 'small')
        oled.text_small("MHTv2-25-001", 0, 12, 'small')
        oled.text_small("Sistema de Monitoreo", 0, 24, 'small')
        oled.text_small("ESP32 + Sensores", 0, 36, 'small')
        oled.show()
        print("✓ Display OLED inicializado")
        time.sleep(2)
        return True
    except Exception as e:
        print(f"⚠ Error inicializando OLED: {e}")
        return False

def initialize_sensors():
    """Inicializa todos los sensores"""
    global ds_devices

    print("Inicializando sensores...")
    print("- DHT22 en pin", DHT22_PIN)

    ds_devices = ds_sensor.scan()
    if ds_devices:
        print(f"  ✓ Encontrados {len(ds_devices)} sensor(es) DS18B20")
        for i, device in enumerate(ds_devices):
            print(f"    Sensor {i}: {device.hex()}")
    else:
        print("  ⚠ No se encontraron sensores DS18B20")

    print("Sensores inicializados\n")

def initialize_wifi():
    """Inicializa WiFi en modo no-bloqueante con manejo robusto de errores"""
    global wlan

    print("Configurando WiFi...")

    try:
        wlan = network.WLAN(network.STA_IF)
        wlan.active(True)

        # Pequeña pausa para que se estabilice
        time.sleep_ms(100)

        if not wlan.isconnected():
            print(f"Intentando conectar a: {SSID}")
            try:
                wlan.connect(SSID, PASSWORD)
                print("Comando de conexión enviado")
            except Exception as e:
                print(f"Error al enviar comando de conexión: {e}")
        else:
            print("WiFi ya estaba conectado")

    except Exception as e:
        print(f"Error inicializando WiFi: {e}")
        print("Continuando sin WiFi...")
        wlan = None

    print("WiFi configurado (modo no-bloqueante)\n")
    return wlan

def update_oled_display():
    """Evento: Actualizar display OLED con tiempo real y barras WiFi"""
    if not oled_initialized:
        return

    try:
        oled.fill(0)

        # Línea 1: Fecha y hora REAL (fuente small)
        date_str, time_str = get_formatted_datetime()

        # Indicar si el tiempo está sincronizado
        if time_synced:
            datetime_text = f"{date_str} {time_str}"
        else:
            datetime_text = f"{date_str} {time_str}*"  # * indica no sincronizado

        oled.text_small(datetime_text, 0, 0, 'small')

        # Línea 2: Número de serie (fuente normal)
        oled.text("MHTv2-25-001", 0, 9)

        # Línea 3: Temperatura Externa (fuente small)
        if current_data.ds18b20_valid:
            temp_out = f"Temp.OUT: {current_data.ds18b20_temp:.2f} C"
        else:
            temp_out = "Temp.OUT: ERROR"
        oled.text_small(temp_out, 0, 27, 'small')

        # Línea 4: Temperatura Interna (fuente small)
        if current_data.dht_valid:
            temp_in = f"Temp.INT: {current_data.dht_temp:.2f} C"
        else:
            temp_in = "Temp.INT: ERROR"
        oled.text_small(temp_in, 0, 36, 'small')

        # Línea 5: Humedad (fuente small)
        if current_data.dht_valid:
            hum_in = f"Humedad: {current_data.dht_humidity:.1f} %"
        else:
            hum_in = "Humedad: ERROR"
        oled.text_small(hum_in, 0, 45, 'small')

        # Línea 6: Estado WiFi con BARRAS
        if wlan and wifi_connected:
            try:
                rssi = wlan.status('rssi')
                bars = get_wifi_signal_bars(rssi)
                barras_visual = crear_barras_wifi(bars)
                status_text = f"WiFi: {barras_visual} {bars}/6"
            except:
                status_text = "WiFi: ERROR"
        elif wifi_reconnecting:
            status_text = "WiFi: REconectando..."
        else:
            status_text = "WiFi: OFF"

        oled.text_small(status_text, 0, 54, 'small')

        oled.show()

    except Exception as e:
        print(f"Error actualizando OLED: {e}")

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
    except Exception:
        current_data.dht_valid = False

    # Leer DS18B20
    if ds_devices:
        try:
            ds_sensor.convert_temp()
            time.sleep_ms(750)
            temp = ds_sensor.read_temp(ds_devices[0])
            if temp is not None:
                current_data.ds18b20_temp = temp
                current_data.ds18b20_valid = True
            else:
                current_data.ds18b20_valid = False
        except Exception:
            current_data.ds18b20_valid = False
    else:
        current_data.ds18b20_valid = False

def check_wifi_event():
    """Evento: Verificar estado WiFi y manejar reconexión con protección de errores"""
    global wifi_connected, wifi_reconnecting, wifi_retry_count

    # Si wlan no se inicializó, salir
    if wlan is None:
        return

    try:
        if wlan.isconnected():
            if not wifi_connected:
                print("\n🌐 WiFi CONECTADO!")
                try:
                    print(f"   IP: {wlan.ifconfig()[0]}")
                    print(f"   RSSI: {wlan.status('rssi')} dBm")
                except:
                    print("   Conectado (sin detalles de IP/RSSI)")

                wifi_connected = True
                wifi_reconnecting = False
                wifi_retry_count = 0

                # Sincronizar tiempo inmediatamente al conectar
                sync_time_from_ntp()

        else:
            if wifi_connected:
                print("\n⚠ WiFi DESCONECTADO")
                wifi_connected = False
                wifi_reconnecting = True

            wifi_retry_count += 1
            if wifi_retry_count >= 3:
                print("🔄 Reintentando conexión WiFi...")
                try:
                    wlan.connect(SSID, PASSWORD)
                except Exception as e:
                    print(f"Error en reconexión: {e}")
                wifi_retry_count = 0
            elif wifi_retry_count == 1:
                wifi_reconnecting = True

    except Exception as e:
        print(f"Error verificando WiFi: {e}")
        # En caso de error grave, marcar como desconectado
        wifi_connected = False
        wifi_reconnecting = False

def update_wifi_led():
    """Evento: Actualizar estado del LED WiFi"""
    global led_state, last_led_blink

    current_time = get_time_ms()

    if wifi_connected:
        wifi_led.on()
    elif wifi_reconnecting:
        if time.ticks_diff(current_time, last_led_blink) >= LED_BLINK_INTERVAL:
            led_state = not led_state
            wifi_led.value(led_state)
            last_led_blink = current_time
    else:
        wifi_led.off()

def display_sensor_data():
    """Mostrar datos de sensores en consola con barras WiFi detalladas"""
    timestamp_str = f"[{current_data.timestamp:06d}]"

    if current_data.dht_valid:
        dht_str = f"DHT22: {current_data.dht_temp:.2f}°C, {current_data.dht_humidity:.1f}%"
    else:
        dht_str = "DHT22: ERROR"

    if current_data.ds18b20_valid:
        ds_str = f"DS18B20: {current_data.ds18b20_temp:.2f}°C"
    else:
        ds_str = "DS18B20: ERROR"

    # Mostrar tiempo real en consola
    if time_synced:
        date_str, time_str = get_formatted_datetime()
        real_time_str = f"TIEMPO: {date_str} {time_str}"
    else:
        real_time_str = "TIEMPO: NO SINCRONIZADO"

    # Estado OLED
    if oled_initialized:
        oled_status = "OLED: ON"
    else:
        oled_status = "OLED: OFF"

    # Estado WiFi DETALLADO con barras
    try:
        if wlan and wifi_connected and wlan.isconnected():
            rssi = wlan.status('rssi')
            bars = get_wifi_signal_bars(rssi)
            clasificacion = obtener_clasificacion_wifi(rssi)
            barras_visual = crear_barras_wifi(bars)
            wifi_str = f"WiFi: {rssi} dBm - {clasificacion} [{barras_visual}] {bars}/6"
        elif wifi_reconnecting:
            wifi_str = "WiFi: RECONECTANDO"
        else:
            wifi_str = "WiFi: OFF"
    except:
        wifi_str = "WiFi: ERROR"

    # Mostrar información
    print(f"{timestamp_str} {dht_str} | {ds_str} | {oled_status}")
    print(f"          {wifi_str} | {real_time_str}")

def main():
    """Función principal con arquitectura de eventos"""
    global last_sensor_read, last_wifi_check, last_oled_update

    print("=== ESP32 Monitor con BARRAS WiFi ===")
    print("DHT22 + DS18B20 + OLED SSD1309 + NTP")
    print("Zona Horaria: UTC-5 (Perú)")
    print("Barras WiFi: 6 niveles de señal")
    print("MicroPython - Un solo núcleo\n")

    # Inicializar componentes
    oled_ok = initialize_oled()
    initialize_sensors()
    wlan = initialize_wifi()

    if wlan is None:
        print("⚠ WiFi no disponible - continuando en modo offline")
    else:
        print("✓ WiFi configurado - sincronización NTP disponible")

    print("Sistema iniciado - Barras WiFi habilitadas")
    if not oled_initialized:
        print("NOTA: OLED no disponible - mostrando en consola")
    print("Presiona Ctrl+C para detener\n")

    # Inicializar tiempos
    start_time = get_time_ms()
    last_sensor_read = start_time
    last_wifi_check = start_time
    last_oled_update = start_time

    try:
        while True:
            current_time = get_time_ms()

            # EVENTO 1: Leer sensores cada 2 segundos
            if time.ticks_diff(current_time, last_sensor_read) >= SENSOR_INTERVAL:
                read_sensors_event()
                display_sensor_data()
                last_sensor_read = current_time

            # EVENTO 2: Verificar WiFi cada 10 segundos (solo si está disponible)
            if wlan and time.ticks_diff(current_time, last_wifi_check) >= WIFI_CHECK_INTERVAL:
                check_wifi_event()
                last_wifi_check = current_time

            # EVENTO 3: Actualizar LED WiFi (continuo)
            update_wifi_led()

            # EVENTO 4: Actualizar OLED cada segundo
            if oled_initialized and time.ticks_diff(current_time, last_oled_update) >= OLED_UPDATE_INTERVAL:
                update_oled_display()
                last_oled_update = current_time

            # EVENTO 5: Verificar sincronización NTP (solo si WiFi disponible)
            if wlan:
                check_ntp_sync()

            time.sleep_ms(10)

    except KeyboardInterrupt:
        print("\n\nDeteniendo programa...")
        wifi_led.off()
        if oled_initialized:
            oled.fill(0)
            oled.text_small("Sistema", 0, 20, 'small')
            oled.text_small("Detenido", 0, 32, 'small')
            oled.show()
            time.sleep(1)
        print("Programa terminado")

    except Exception as e:
        print(f"\nError crítico: {e}")
        wifi_led.off()

if __name__ == "__main__":
    main()
