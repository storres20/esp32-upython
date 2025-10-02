# ws_client.py - Librería WebSocket optimizada para ESP32 con SSL
# Guarda este archivo en el ESP32 con Thonny

import socket
import ssl
import struct
import binascii
import time

class WebSocket:
    def __init__(self):
        self.sock = None
        self.connected = False  # AGREGADO
        self.connected = False

    def connect(self, url):
        """Conecta a servidor WebSocket (ws:// o wss://)"""
        try:
            # Parsear URL
            if url.startswith("wss://"):
                host = url[6:].split("/")[0]
                port = 443
                use_ssl = True
                path = "/"
            elif url.startswith("ws://"):
                host = url[5:].split("/")[0]
                port = 80
                use_ssl = False
                path = "/"
            else:
                raise ValueError("URL debe empezar con ws:// o wss://")

            # Separar puerto si existe
            if ":" in host and "/" not in host:
                host, port = host.split(":")
                port = int(port)

            print(f"Conectando a {host}:{port} (SSL: {use_ssl})")

            # Crear socket TCP
            addr = socket.getaddrinfo(host, port)[0][-1]
            self.sock = socket.socket()
            self.sock.settimeout(15)
            self.sock.connect(addr)

            print("Socket conectado")

            # Aplicar SSL si es necesario
            if use_ssl:
                print("Aplicando SSL...")
                try:
                    # Intentar con SNI
                    self.sock = ssl.wrap_socket(self.sock, server_hostname=host)
                    print("SSL aplicado con SNI")
                except:
                    # Fallback sin SNI
                    try:
                        self.sock = ssl.wrap_socket(self.sock)
                        print("SSL aplicado sin SNI")
                    except Exception as e:
                        print(f"Error SSL: {e}")
                        raise

            # WebSocket handshake
            print("Enviando handshake WebSocket...")
            key = binascii.b2a_base64(b'0123456789ABCDEF')[:-1]

            request = (
                f"GET {path} HTTP/1.1\r\n"
                f"Host: {host}\r\n"
                f"Upgrade: websocket\r\n"
                f"Connection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {key.decode()}\r\n"
                f"Sec-WebSocket-Version: 13\r\n"
                f"\r\n"
            )

            self.sock.send(request.encode())

            # Leer respuesta con timeout
            response = b""
            start = time.ticks_ms()
            while time.ticks_diff(time.ticks_ms(), start) < 5000:
                try:
                    chunk = self.sock.recv(1024)
                    response += chunk
                    if b"\r\n\r\n" in response:
                        break
                except:
                    time.sleep_ms(100)

            if b"101" not in response or b"Upgrade" not in response:
                print(f"Handshake fallido. Respuesta: {response[:200]}")
                raise Exception("WebSocket handshake failed")

            print("Handshake exitoso")
            self.connected = True
            return True

        except Exception as e:
            print(f"Error en connect(): {e}")
            if self.sock:
                try:
                    self.sock.close()
                except:
                    pass
            self.sock = None
            self.connected = False
            return False

    def send(self, data):
        """Envía mensaje por WebSocket"""
        if not self.connected or not self.sock:
            return False

        try:
            if isinstance(data, str):
                data = data.encode()

            # Frame WebSocket básico (texto, con mask)
            frame = bytearray()
            frame.append(0x81)  # FIN + Text frame

            length = len(data)
            if length < 126:
                frame.append(0x80 | length)  # Mask bit + length
            elif length < 65536:
                frame.append(0x80 | 126)
                frame.extend(struct.pack(">H", length))
            else:
                frame.append(0x80 | 127)
                frame.extend(struct.pack(">Q", length))

            # Mask simple (4 bytes de ceros para simplificar)
            mask = b'\x00\x00\x00\x00'
            frame.extend(mask)

            # Data (no necesita XOR si mask es 0x00000000)
            frame.extend(data)

            self.sock.send(frame)
            return True

        except Exception as e:
            print(f"Error en send(): {e}")
            self.connected = False
            return False

    def close(self):
        """Cierra la conexión WebSocket"""
        if self.sock:
            try:
                # Enviar frame de cierre
                self.sock.send(b'\x88\x00')
                self.sock.close()
            except:
                pass
            self.sock = None
        self.connected = False
