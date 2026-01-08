# ESP32 Monitor con WebSocket usando ws_client.py (DUAL CORE)
# show ERROR on console and oled display when a sensor is disconnected instead of showing just 0.0

import network
import machine
import time
import dht
import onewire
import ds18x20
import json
import _thread
from machine import Pin, SoftI2C
from ws_client import WebSocket

# Intentar importar ssd1306
try:
    import ssd1306
    OLED_AVAILABLE = True
    print("✓ Librería ssd1306 encontrada")
except ImportError:
    OLED_AVAILABLE = False
    print("⚠ Librería ssd1306 no encontrada")

# Configuración
SSID = "motog35"
PASSWORD = "12345678"
WEBSOCKET_URL = "wss://bio-data-production.up.railway.app/"
USERNAME = "MHT-prueba"

# Pines
DHT22_PIN = 4
DS18B20_PIN = 5
WIFI_LED_PIN = 2
MC38_SENSOR_PIN = 15
MC38_LED_PIN = 13
OLED_SCL_PIN = 22
OLED_SDA_PIN = 21

# Zona horaria (Perú UTC-5)
TIMEZONE_OFFSET = -5 * 3600

# Estado del sistema (compartido entre núcleos)
time_synced = False
wifi_connected = False
door_closed = False
wlan = None
ws = None
network_thread_running = False

# Lock para datos compartidos
data_lock = _thread.allocate_lock()

# Inicializar OLED
oled_initialized = False
oled = None
if OLED_AVAILABLE:
    try:
        i2c = SoftI2C(scl=Pin(OLED_SCL_PIN), sda=Pin(OLED_SDA_PIN))
        oled = ssd1306.SSD1306_I2C(128, 64, i2c)
        oled_initialized = True
        print("✓ OLED inicializado")
    except Exception as e:
        oled_initialized = False
        print(f"⚠ Error OLED: {e}")

# Inicializar sensores
dht22 = dht.DHT11(Pin(DHT22_PIN))
ds_pin = Pin(DS18B20_PIN)
ds_sensor = ds18x20.DS18X20(onewire.OneWire(ds_pin))
wifi_led = Pin(WIFI_LED_PIN, Pin.OUT)
mc38_sensor = Pin(MC38_SENSOR_PIN, Pin.IN, Pin.PULL_DOWN)
mc38_led = Pin(MC38_LED_PIN, Pin.OUT)

wifi_led.off()
mc38_led.off()

# Datos de sensores
class SensorData:
    def __init__(self):
        self.dht_temp = 0.0
        self.dht_humidity = 0.0
        self.ds18b20_temp = 0.0
        self.dht_valid = False
        self.ds18b20_valid = False

current_data = SensorData()
ds_devices = []

def get_wifi_signal_bars(rssi):
    """Convierte RSSI a barras (0-6)"""
    if rssi >= -50:
        return 6
    elif rssi >= -60:
        return 5
    elif rssi >= -70:
        return 4
    elif rssi >= -80:
        return 3
    elif rssi >= -90:
        return 2
    else:
        return 1

def crear_barras_wifi(barras_activas):
    """Crea representación ASCII de barras WiFi"""
    barras = ""
    for i in range(6):
        barras += "X" if i < barras_activas else "O"
    return barras

def sync_time():
    """Sincronizar tiempo con NTP"""
    global time_synced
    try:
        import ntptime
        ntptime.settime()
        time_synced = True
        t = time.localtime()
        print(f"✓ Tiempo: {t[2]:02d}/{t[1]:02d}/{t[0]} {t[3]:02d}:{t[4]:02d}")
        return True
    except Exception as e:
        print(f"⚠ Error NTP: {e}")
        return False

def init_wifi():
    """Inicializa WiFi (sin bloquear)"""
    global wifi_connected, wlan
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)

    if not wlan.isconnected():
        print(f"Conectando WiFi a {SSID}...")
        wlan.connect(SSID, PASSWORD)

    return wlan

def init_sensors():
    """Inicializa sensores - Primera detección"""
    global ds_devices, door_closed
    print("\nInicializando sensores...")

    # DS18B20 - Primera detección
    try:
        ds_devices = ds_sensor.scan()
        if ds_devices:
            print(f"✓ DS18B20: {len(ds_devices)} sensor(es)")
            for i, dev in enumerate(ds_devices):
                print(f"  Sensor {i}: {dev.hex()}")
        else:
            print("⚠ DS18B20: No encontrado (se seguirá buscando)")
    except Exception as e:
        print(f"⚠ DS18B20: Error al escanear - {e}")
        ds_devices = []

    # DHT22 - Solo informar, se detectará en primera lectura
    print("⏳ DHT22: Se verificará en primera lectura")

    # MC-38
    try:
        door_closed = mc38_sensor.value()
        if door_closed:
            mc38_led.off()
            print("✓ Puerta: CERRADA (LED OFF)")
        else:
            mc38_led.on()
            print("⚠ Puerta: ABIERTA (LED ON)")
    except Exception as e:
        print(f"⚠ MC-38: Error - {e}")
        door_closed = False

def detect_sensors():
    """Detecta sensores conectados dinámicamente"""
    global ds_devices

    # Detectar DS18B20
    try:
        devices = ds_sensor.scan()
        if devices != ds_devices:
            ds_devices = devices
            if ds_devices:
                print(f"🔍 DS18B20 detectado: {len(ds_devices)} sensor(es)")
                for i, dev in enumerate(ds_devices):
                    print(f"  Sensor {i}: {dev.hex()}")
            else:
                print("⚠ DS18B20 desconectado")
    except Exception as e:
        print(f"Error escaneando DS18B20: {e}")
        ds_devices = []

def read_sensors():
    """Lee sensores (no bloqueante)"""
    # DHT22
    try:
        dht22.measure()
        with data_lock:
            current_data.dht_temp = dht22.temperature()
            current_data.dht_humidity = dht22.humidity()
            current_data.dht_valid = True
    except:
        with data_lock:
            current_data.dht_valid = False

    # DS18B20
    if ds_devices:
        try:
            ds_sensor.convert_temp()
            time.sleep_ms(750)
            temp = ds_sensor.read_temp(ds_devices[0])
            if temp and temp != -127.0:
                with data_lock:
                    current_data.ds18b20_temp = temp
                    current_data.ds18b20_valid = True
            else:
                with data_lock:
                    current_data.ds18b20_valid = False
        except:
            with data_lock:
                current_data.ds18b20_valid = False
    else:
        # Si no hay dispositivos, marcar como inválido
        with data_lock:
            current_data.ds18b20_valid = False

def check_door():
    """Verifica estado de la puerta"""
    global door_closed
    state = mc38_sensor.value()

    if state != door_closed:
        door_closed = state
        if door_closed:
            mc38_led.off()
            print("\n🚪 PUERTA CERRADA - LED OFF")
        else:
            mc38_led.on()
            print("\n⚠️  PUERTA ABIERTA - LED ON")

def update_oled():
    """Actualiza pantalla OLED"""
    if not oled_initialized:
        return

    try:
        oled.fill(0)

        # Línea 1: Fecha y hora
        if time_synced:
            t = time.localtime(time.time() + TIMEZONE_OFFSET)
            oled.text_small(f"{t[2]:02d}/{t[1]:02d}/{t[0]%100:02d} {t[3]:02d}:{t[4]:02d}", 0, 0, 'small')
        else:
            oled.text_small("NO SYNC", 0, 0, 'small')

        # Línea 2: ID
        oled.text(USERNAME, 0, 9)

        # Línea 3: Temp OUT
        with data_lock:
            if current_data.ds18b20_valid:
                oled.text_small(f"T.OUT: {current_data.ds18b20_temp:.1f}C", 0, 27, 'small')
            else:
                oled.text_small("T.OUT: ERROR", 0, 27, 'small')

            # Línea 4: Temp IN
            if current_data.dht_valid:
                oled.text_small(f"T.IN: {current_data.dht_temp:.1f}C", 0, 36, 'small')
            else:
                oled.text_small("T.IN: ERROR", 0, 36, 'small')

            # Línea 5: Humedad
            if current_data.dht_valid:
                oled.text_small(f"Hum: {current_data.dht_humidity:.0f}%", 0, 45, 'small')
            else:
                oled.text_small("Hum: ERROR", 0, 45, 'small')

        # Línea 6: Estado
        if wlan and wifi_connected:
            rssi = wlan.status('rssi')
            bars = get_wifi_signal_bars(rssi)
            barras_visual = crear_barras_wifi(bars)
            ws_status = "WS:OK" if (ws and ws.connected) else "WS:--"
            oled.text_small(f"WiFi:{barras_visual} {bars}/6 {ws_status}", 0, 54, 'small')
        else:
            oled.text_small("WiFi: DESCONECTADO", 0, 54, 'small')

        oled.show()
    except Exception as e:
        print(f"Error OLED: {e}")

# ============================================
# NÚCLEO 0: Red y WebSocket (bloqueante OK)
# ============================================
def network_thread():
    """Hilo que maneja WiFi y WebSocket en núcleo separado"""
    global wifi_connected, ws, wlan, network_thread_running, time_synced

    network_thread_running = True
    print("🔷 Núcleo de Red iniciado (Core 0)")

    # Crear WebSocket
    ws = WebSocket()

    last_wifi_check = time.ticks_ms()
    last_send = time.ticks_ms()
    last_ping = time.ticks_ms()
    last_ntp_sync = time.ticks_ms()
    reconnect_attempts = 0
    ws_reconnect_delay = 5000  # 5 segundos entre intentos
    last_ws_attempt = 0
    wifi_was_connected = False  # Para detectar reconexiones

    try:
        while network_thread_running:
            now = time.ticks_ms()

            # ===== VERIFICAR WIFI =====
            if time.ticks_diff(now, last_wifi_check) >= 5000:  # Cada 5s
                try:
                    if wlan and wlan.isconnected():
                        if not wifi_connected:
                            print("\n✅ WiFi RECONECTADO")
                            print(f"   IP: {wlan.ifconfig()[0]}")
                            print(f"   RSSI: {wlan.status('rssi')} dBm")
                            wifi_connected = True
                            wifi_led.on()
                            reconnect_attempts = 0

                            # CRÍTICO: Si WiFi se reconectó, RECREAR WebSocket
                            if wifi_was_connected:
                                print("🔄 Recreando WebSocket después de reconexión WiFi...")
                                try:
                                    ws.close()
                                except:
                                    pass
                                time.sleep_ms(500)
                                ws = WebSocket()  # Nuevo objeto limpio
                                print("✓ WebSocket recreado")

                            # Sincronizar tiempo
                            if not time_synced:
                                sync_time()

                        wifi_was_connected = True
                    else:
                        if wifi_connected:
                            print("\n⚠️  WiFi DESCONECTADO")
                            wifi_connected = False
                            wifi_was_connected = False
                            wifi_led.off()
                            if ws:
                                try:
                                    ws.close()
                                except:
                                    pass
                                ws.connected = False

                        # Reintentar conexión
                        print("🔄 Reintentando WiFi...")
                        if wlan:
                            try:
                                wlan.disconnect()  # Limpiar conexión anterior
                                time.sleep_ms(200)
                            except:
                                pass
                            wlan.connect(SSID, PASSWORD)

                except Exception as e:
                    print(f"Error verificando WiFi: {e}")

                last_wifi_check = now

            # ===== SINCRONIZAR NTP CADA 1 HORA =====
            if wifi_connected and time.ticks_diff(now, last_ntp_sync) >= 3600000:
                sync_time()
                last_ntp_sync = now

            # ===== WEBSOCKET =====
            if wifi_connected:
                # Conectar WebSocket si está desconectado
                if not ws.connected:
                    # Esperar delay entre intentos
                    if time.ticks_diff(now, last_ws_attempt) >= ws_reconnect_delay:
                        reconnect_attempts += 1
                        print(f"\n🔌 Conectando WebSocket (intento {reconnect_attempts})...")
                        last_ws_attempt = now

                        try:
                            # Agregar timeout de 15 segundos para connect
                            connect_start = time.ticks_ms()

                            # connect() es bloqueante, pero está en núcleo separado
                            if ws.connect(WEBSOCKET_URL):
                                connect_time = time.ticks_diff(time.ticks_ms(), connect_start)
                                print(f"✓ WebSocket conectado en {connect_time}ms")

                                time.sleep_ms(500)
                                intro = json.dumps({"username": USERNAME})
                                ws.send(intro)
                                print(f"✓ Username enviado: {USERNAME}")

                                reconnect_attempts = 0
                                ws_reconnect_delay = 5000  # Resetear delay
                                last_ping = now  # Resetear ping
                                last_send = now  # Resetear envío
                            else:
                                print(f"❌ WebSocket no conectado (intento {reconnect_attempts})")

                                # Estrategia de backoff exponencial
                                if reconnect_attempts >= 5:
                                    ws_reconnect_delay = 60000  # 60s después de 5 fallos
                                    print("⏳ Esperando 60s antes del próximo intento...")
                                elif reconnect_attempts >= 3:
                                    ws_reconnect_delay = 30000  # 30s después de 3 fallos
                                    print("⏳ Esperando 30s antes del próximo intento...")
                                else:
                                    ws_reconnect_delay = 5000   # 5s normal

                                # Recrear WebSocket después de varios fallos
                                if reconnect_attempts >= 3:
                                    print("🔄 Recreando WebSocket por múltiples fallos...")
                                    try:
                                        ws.close()
                                    except:
                                        pass
                                    time.sleep_ms(500)
                                    ws = WebSocket()

                        except Exception as e:
                            print(f"❌ Error conectando WebSocket: {e}")
                            ws.connected = False

                            # Recrear WebSocket en caso de error
                            try:
                                ws.close()
                            except:
                                pass
                            time.sleep_ms(500)
                            ws = WebSocket()

                # Enviar datos cada 2s si está conectado
                if ws.connected and time.ticks_diff(now, last_send) >= 2000:
                    try:
                        # Formato ISO UTC
                        t = time.gmtime()
                        datetime_utc = f"{t[0]:04d}-{t[1]:02d}-{t[2]:02d}T{t[3]:02d}:{t[4]:02d}:{t[5]:02d}Z"

                        # ⬇️ CAMBIO CRÍTICO: Enviar None para sensores inválidos
                        with data_lock:
                            data = {
                                "username": USERNAME,
                                "dsTemperature": round(current_data.ds18b20_temp, 1) if current_data.ds18b20_valid else None,
                                "temperature": round(current_data.dht_temp, 1) if current_data.dht_valid else None,
                                "humidity": int(round(current_data.dht_humidity, 0)) if current_data.dht_valid else None,
                                "datetime": datetime_utc,
                                "doorStatus": "closed" if door_closed else "open"
                            }

                        json_str = json.dumps(data)

                        if ws.send(json_str):
                            # Mostrar valores o "ERROR" en consola
                            ds_temp_str = f"{data['dsTemperature']}°C" if data['dsTemperature'] is not None else "ERROR"
                            dht_temp_str = f"{data['temperature']}°C" if data['temperature'] is not None else "ERROR"
                            humidity_str = f"{data['humidity']}%" if data['humidity'] is not None else "ERROR"
                            door_icon = "🚪✅" if door_closed else "🚪⚠️"

                            print(f"📤 WS | T.OUT: {ds_temp_str} | T.IN: {dht_temp_str} | H: {humidity_str} | {door_icon}")
                        else:
                            print("❌ Error enviando datos")
                            ws.connected = False

                    except Exception as e:
                        print(f"❌ Error en envío: {e}")
                        ws.connected = False

                    last_send = now

                # Ping cada 30s
                if ws.connected and time.ticks_diff(now, last_ping) >= 30000:
                    try:
                        ws.send('{"type":"ping"}')
                        print("📶 Ping enviado")
                    except:
                        ws.connected = False
                    last_ping = now

            else:
                # Sin WiFi, marcar WebSocket desconectado
                if ws and ws.connected:
                    ws.connected = False
                    print("⚠️ WebSocket marcado como desconectado (sin WiFi)")

            time.sleep_ms(100)  # Pequeña pausa para no saturar

    except Exception as e:
        print(f"💥 Error crítico en núcleo de red: {e}")
    finally:
        network_thread_running = False
        print("🔷 Núcleo de Red detenido")

# ============================================
# NÚCLEO 1: Sensores y Display (Main)
# ============================================
def main():
    global wlan

    print("\n" + "="*50)
    print("ESP32 Monitor DUAL CORE con WebSocket SSL")
    print("="*50)
    print(f"URL: {WEBSOCKET_URL}")
    print(f"Username: {USERNAME}")
    print(f"DHT22: GPIO{DHT22_PIN}")
    print(f"DS18B20: GPIO{DS18B20_PIN}")
    print(f"MC-38: GPIO{MC38_SENSOR_PIN} (LED: GPIO{MC38_LED_PIN})")
    print("="*50 + "\n")

    # Inicializar sensores
    init_sensors()

    # Inicializar WiFi
    wlan = init_wifi()

    # Esperar conexión inicial WiFi (máximo 15s)
    print("Esperando conexión WiFi inicial...")
    timeout = 15
    while not wlan.isconnected() and timeout > 0:
        time.sleep(1)
        timeout -= 1

    if wlan.isconnected():
        global wifi_connected
        wifi_connected = True
        print(f"✓ WiFi conectado: {wlan.ifconfig()[0]}")
        wifi_led.on()
        sync_time()
    else:
        print("⚠ WiFi no conectado inicialmente (se reintentará)")

    # Iniciar hilo de red en Core 0
    print("\n🚀 Iniciando núcleo de red...")
    _thread.start_new_thread(network_thread, ())
    time.sleep(1)

    print("\n" + "="*50)
    print("Sistema iniciado - Presiona Ctrl+C para detener")
    print("🔶 Core 1: Sensores y Display")
    print("🔷 Core 0: WiFi y WebSocket")
    print("="*50 + "\n")

    # Timers para Core 1
    last_sensor = time.ticks_ms()
    last_door = time.ticks_ms()
    last_oled = time.ticks_ms()
    last_detect = time.ticks_ms()

    try:
        while True:
            now = time.ticks_ms()

            # Detectar sensores cada 5 segundos
            if time.ticks_diff(now, last_detect) >= 5000:
                detect_sensors()
                last_detect = now

            # Leer sensores cada 2s
            if time.ticks_diff(now, last_sensor) >= 2000:
                read_sensors()
                last_sensor = now

            # Puerta cada 100ms
            if time.ticks_diff(now, last_door) >= 100:
                check_door()
                last_door = now

            # OLED cada 1s
            if time.ticks_diff(now, last_oled) >= 1000:
                update_oled()
                last_oled = now

            time.sleep_ms(10)

    except KeyboardInterrupt:
        print("\n\n" + "="*50)
        print("Deteniendo sistema...")
        print("="*50)

        # Detener hilo de red
        global network_thread_running
        network_thread_running = False
        time.sleep(1)

        # Limpiar
        if ws:
            ws.close()
        wifi_led.off()
        mc38_led.off()

        if oled_initialized:
            oled.fill(0)
            oled.text_small("Sistema", 0, 20, 'small')
            oled.text_small("Detenido", 0, 32, 'small')
            oled.show()
            time.sleep(1)

        print("Sistema detenido")

if __name__ == "__main__":
    main()
