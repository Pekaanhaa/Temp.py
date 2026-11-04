# pip install pyserial mysql-connector-python
import time
import logging
from datetime import datetime
from dotenv import load_dotenv

import os
import serial
import mysql.connector
from mysql.connector import Error
 
# ---------------- Configuracoes ----------------
PORTA_SERIAL = "COM3"        # Linux: "/dev/ttyUSB0" ou "/dev/ttyACM0"
BAUDRATE = 9600
INTERVALO_MEDIA = 60         # segundos
 
caminho_env = os.path.abspath(os.path.join(os.path.dirname(__file__), '.env'))

print(f"Procurando arquivo .env em: {caminho_env}")
load_dotenv(caminho_env)


def obter_conexao():
    try:
        conexao = mysql.connector.connect(
            host=os.getenv("DB_HOST"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASS"),
            database=os.getenv("DB_NAME")
        )

        if conexao.is_connected():
            print("Conectado ao MySQL!!!")
            return conexao

    except Exception as e:
        print(f"Erro ao conectar o Banco de dados: {e}")

    return None


def garantir_conexao(conn):
    """Reconecta se a conexao caiu ou ainda nao existe."""
    try:
        if conn is None or not conn.is_connected():
            raise Error("desconectado")
        conn.ping(reconnect=True, attempts=3, delay=2)
        return conn
    except Error:
        logging.warning("Conectando ao MySQL...")
        nova = obter_conexao()
        if nova is None:
            raise Error("Falha ao conectar ao MySQL")
        return nova


def criar_tabela(conexao):
    cursor = conexao.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS historico_distancia (
            id INT AUTO_INCREMENT PRIMARY KEY,
            valor_cm INT NOT NULL,
            registrado_em DATETIME NOT NULL
        )
    """)
    conexao.commit()
    cursor.close()

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
 
 
# ---------------- Banco de dados ----------------

def salvar_leitura(conn, momento, temp):
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO temperatura_raw (data_hora, temperatura) VALUES (%s, %s)",
        (momento, round(temp, 2)),
    )
    conn.commit()
    cur.close()
 
 
def salvar_media(conn, momento, leituras):
    media = sum(leituras) / len(leituras)
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO temperatura_media
           (data_hora, media, minima, maxima, amostras)
           VALUES (%s, %s, %s, %s, %s)""",
        (momento, round(media, 2), round(min(leituras), 2),
         round(max(leituras), 2), len(leituras)),
    )
    conn.commit()
    cur.close()
    logging.info("Media do minuto: %.2f C (%d amostras)", media, len(leituras))
 
 
# ---------------- Serial ----------------
def abrir_serial():
    while True:
        try:
            ser = serial.Serial(PORTA_SERIAL, BAUDRATE, timeout=3)
            time.sleep(2)           # o Arduino reinicia ao abrir a serial
            ser.reset_input_buffer()
            logging.info("Serial aberta em %s", PORTA_SERIAL)
            return ser
        except serial.SerialException as e:
            logging.error("Falha ao abrir serial: %s. Tentando em 5s...", e)
            time.sleep(5)
 
 
def ler_temperatura(ser):
    """Le uma linha da serial e converte para float. Retorna None se invalida."""
    linha = ser.readline().decode("utf-8", errors="ignore").strip()
    if not linha:
        return None
    try:
        temp = float(linha)
    except ValueError:
        logging.warning("Linha invalida: %r", linha)
        return None
    if not -10 <= temp <= 110:      # faixa do LM35
        logging.warning("Valor fora da faixa: %.2f", temp)
        return None
    return temp
 
 
# ---------------- Loop principal ----------------
def main():
    ser = abrir_serial()
    conn = None
    leituras_minuto = []
    inicio_janela = time.monotonic()
 
    try:
        while True:
            try:
                temp = ler_temperatura(ser)
            except serial.SerialException as e:
                logging.error("Erro na serial: %s", e)
                ser.close()
                ser = abrir_serial()
                continue
 
            if temp is None:
                continue
 
            agora = datetime.now()
            leituras_minuto.append(temp)
            logging.info("Temperatura: %.2f C", temp)
 
            try:
                conn = garantir_conexao(conn)
                salvar_leitura(conn, agora, temp)
 
                if time.monotonic() - inicio_janela >= INTERVALO_MEDIA:
                    salvar_media(conn, agora, leituras_minuto)
                    leituras_minuto = []
                    inicio_janela = time.monotonic()
 
            except Error as e:
                logging.error("Erro no MySQL: %s", e)
                conn = None
 
    except KeyboardInterrupt:
        logging.info("Encerrando...")
    finally:
        ser.close()
        if conn and conn.is_connected():
            conn.close()
 
 
if __name__ == "__main__":
    main()