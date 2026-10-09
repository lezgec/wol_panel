import socket

def iniciar_monitor():
    # Crear un socket UDP
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    
    # Permitir reutilizar la dirección/puerto por si se quedó colgado
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    # Escuchar en todas las interfaces de red (0.0.0.0), puerto estándar WoL (9)
    try:
        sock.bind(('0.0.0.0', 9))
    except Exception as e:
        print(f"[ERROR] No se pudo vincular al puerto 9: {e}")
        return
    
    print("==================================================")
    print(" 🎧 ESPÍA WAKE-ON-LAN INICIADO")
    print("==================================================")
    print("Escuchando paquetes mágicos en el puerto UDP 9...")
    print("Presiona Ctrl+C para salir.\n")
    
    try:
        while True:
            # Esperar a recibir datos
            data, addr = sock.recvfrom(1024)
            if len(data) < 102 or data[:6] != b'\xff' * 6 or data[6:102] != data[6:12] * 16:
                print(f"Datagrama UDP sin formato WoL desde {addr[0]}:{addr[1]}")
                continue
            
            print(f"✅ ¡PAQUETE MÁGICO DETECTADO!")
            print(f"   -> Origen del paquete: {addr[0]}:{addr[1]}")
            
            # Convertir el paquete a formato hexadecimal
            hex_data = data.hex()
            
            # El paquete mágico empieza con 6 bytes en 'FF' (12 caracteres en hex)
            header = hex_data[:12]
            
            # La MAC a la que va dirigida ocupa los siguientes 6 bytes (12 caracteres)
            mac_target = hex_data[12:24]
            
            # Formatear la MAC a estilo XX:XX:XX:XX:XX:XX para que sea fácil de leer
            mac_formatted = ':'.join(mac_target[i:i+2] for i in range(0, 12, 2)).upper()
            
            print(f"   -> Cabecera WoL : {header.upper()}")
            print(f"   -> MAC destino  : {mac_formatted}")
            print("-" * 50)
            
    except KeyboardInterrupt:
        print("\n⏹️ Monitor detenido. Saliendo...")
    finally:
        sock.close()

if __name__ == '__main__':
    iniciar_monitor()
