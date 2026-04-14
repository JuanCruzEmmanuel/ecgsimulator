import sys
import serial
import numpy as np
from collections import deque
from PyQt5 import QtWidgets, QtCore
import pyqtgraph as pg
from scipy.signal import find_peaks
import asyncio
import threading
from bleak import BleakClient, BleakScanner
from lectura import lectura
PORT        = 'COM5'
BAUDRATE    = 115200
WINDOW_SEC  = 5
SAMPLE_RATE = 400
POLL_MS     = 5

MAX_POINTS  = WINDOW_SEC * SAMPLE_RATE

CHAR_UUID   = lectura("UID.txt") #por una cuestion de seguridad
ESP32_NAME  = "ESP32_ECG"

class ECGMonitor(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ECG Monitor")
        self.resize(1000, 520)

        self.data   = deque([0.0] * MAX_POINTS, maxlen=MAX_POINTS)
        self.t_data = deque([0.0] * MAX_POINTS, maxlen=MAX_POINTS)
        self.t0     = None

        self.ble_client   = None
        self.ble_status   = "desconectado"

        try:
            self.ser = serial.Serial(PORT, BAUDRATE, timeout=0)
        except serial.SerialException as e:
            QtWidgets.QMessageBox.critical(self, "Error", str(e))
            sys.exit(1)

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        layout = QtWidgets.QVBoxLayout(central)
        layout.setContentsMargins(8, 8, 8, 8)

        # ── Header ────────────────────────────────────────────────────────
        header = QtWidgets.QHBoxLayout()

        self.bpm_label = QtWidgets.QLabel("BPM: --")
        self.bpm_label.setStyleSheet(
            "font-size: 24px; font-weight: bold; color: #e05c3a; padding: 4px 12px;"
        )
        header.addWidget(self.bpm_label)
        header.addStretch()

        # Estado BLE
        self.ble_label = QtWidgets.QLabel("BLE: desconectado")
        self.ble_label.setStyleSheet("font-size: 12px; color: gray; padding: 4px 8px;")
        header.addWidget(self.ble_label)

        # Botón conectar BLE
        self.ble_btn = QtWidgets.QPushButton("Conectar BLE")
        self.ble_btn.setFixedWidth(120)
        self.ble_btn.setStyleSheet("font-size: 13px; padding: 2px 8px;")
        self.ble_btn.clicked.connect(self.connect_ble)
        header.addWidget(self.ble_btn)


        # Boton ruido
        self.line_noise_btn_50 = QtWidgets.QPushButton("50Hz Noise")
        self.line_noise_btn_50.setFixedWidth(120)
        self.line_noise_btn_50.setStyleSheet("font-size: 13px; padding: 2px 8px;")
        self.line_noise_btn_50.clicked.connect(self.set_noise_50) #Cuando presiono el boton donde lo conecto
        header.addWidget(self.line_noise_btn_50) #Incrusto el boton
        
        
        self.line_noise_btn_60 = QtWidgets.QPushButton("60Hz Noise")
        self.line_noise_btn_60.setFixedWidth(120)
        self.line_noise_btn_60.setStyleSheet("font-size: 13px; padding: 2px 8px;")
        self.line_noise_btn_60.clicked.connect(self.set_noise_60) #Cuando presiono el boton donde lo conecto
        header.addWidget(self.line_noise_btn_60) #Incrusto el boton
        
        self.ECG_BTN = QtWidgets.QPushButton("ECG NORMAL")
        self.ECG_BTN.setFixedWidth(120)
        self.ECG_BTN.setStyleSheet("font-size: 13px; padding: 2px 8px;")
        self.ECG_BTN.clicked.connect(self.set_ECG) #Cuando presiono el boton donde lo conecto
        header.addWidget(self.ECG_BTN) #Incrusto el boton


        # Spinbox BPM
        self.bpm_spin = QtWidgets.QSpinBox()
        self.bpm_spin.setRange(10, 300)
        self.bpm_spin.setValue(60)
        self.bpm_spin.setPrefix("BPM: ")
        self.bpm_spin.setFixedWidth(110)
        self.bpm_spin.setStyleSheet("font-size: 14px; padding: 2px 6px;")

        send_btn = QtWidgets.QPushButton("Enviar")
        send_btn.setFixedWidth(80)
        send_btn.setStyleSheet("font-size: 14px; padding: 2px 8px;")
        send_btn.clicked.connect(self.send_bpm)
        self.bpm_spin.lineEdit().returnPressed.connect(self.send_bpm)

        header.addWidget(QtWidgets.QLabel("Cambiar frecuencia:"))
        header.addWidget(self.bpm_spin)
        header.addWidget(send_btn)

        layout.addLayout(header)

        # ── Plot ──────────────────────────────────────────────────────────
        pg.setConfigOptions(antialias=True, background='#1a1a2e', foreground='#c0bdb5')
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setLabel('left',   'Amplitud', units='')
        self.plot_widget.setLabel('bottom', 'Tiempo',   units='s')
        self.plot_widget.setYRange(-20, 275)
        self.plot_widget.showGrid(x=True, y=True, alpha=0.2)
        self.plot_widget.getAxis('left').setWidth(45)

        pen = pg.mkPen(color='#e05c3a', width=1.5)
        self.curve = self.plot_widget.plot(pen=pen)
        layout.addWidget(self.plot_widget)

        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.update)
        self.timer.start(POLL_MS)

        self.bpm_timer = QtCore.QTimer()
        self.bpm_timer.timeout.connect(self.calc_bpm)
        self.bpm_timer.start(2500)

        # Loop asyncio en hilo separado para BLE
        self.loop = asyncio.new_event_loop()
        t = threading.Thread(target=self.loop.run_forever, daemon=True)
        t.start()

    # ── BLE: conectar ─────────────────────────────────────────────────────
    def connect_ble(self):
        self.ble_label.setText("BLE: buscando...")
        self.ble_btn.setEnabled(False)
        asyncio.run_coroutine_threadsafe(self._ble_connect(), self.loop)

    def set_noise_50(self):
        "Si esta conectado puedo enviar"
        if self.ble_client and self.ble_client.is_connected:
            #print(val)
            asyncio.run_coroutine_threadsafe(
                self._ble_send("NOISE_50"), self.loop
            )
        else:
            print("No se encuentra conectado....")
            
    def set_noise_60(self):
        "Si esta conectado puedo enviar"
        if self.ble_client and self.ble_client.is_connected:
            #print(val)
            asyncio.run_coroutine_threadsafe(
                self._ble_send("NOISE_60"), self.loop
            )
        else:
            print("No se encuentra conectado....")
            
    def set_ECG(self):
        "Si esta conectado puedo enviar"
        if self.ble_client and self.ble_client.is_connected:
            #print(val)
            asyncio.run_coroutine_threadsafe(
                self._ble_send("ECG_NORMAL"), self.loop
            )
        else:
            print("No se encuentra conectado....")

    async def _ble_connect(self):
        try:
            device = await BleakScanner.find_device_by_name(ESP32_NAME, timeout=8)
            if device is None:
                self._set_ble_status("no encontrado", "red")
                return
            self.ble_client = BleakClient(device, disconnected_callback=self._on_ble_disconnect)
            await self.ble_client.connect()
            self._set_ble_status("conectado", "#4caf50")
        except Exception as e:
            self._set_ble_status(f"error: {e}", "red")

    def _on_ble_disconnect(self, client):
        self.ble_client = None
        self._set_ble_status("desconectado", "gray")

    def _set_ble_status(self, text, color):
        # Actualizar UI desde hilo BLE de forma segura
        QtCore.QMetaObject.invokeMethod(
            self.ble_label, "setText",
            QtCore.Qt.QueuedConnection,
            QtCore.Q_ARG(str, f"BLE: {text}")
        )
        QtCore.QMetaObject.invokeMethod(
            self.ble_label, "setStyleSheet",
            QtCore.Qt.QueuedConnection,
            QtCore.Q_ARG(str, f"font-size: 12px; color: {color}; padding: 4px 8px;")
        )
        QtCore.QMetaObject.invokeMethod(
            self.ble_btn, "setEnabled",
            QtCore.Qt.QueuedConnection,
            QtCore.Q_ARG(bool, self.ble_client is None)
        )

    # ── Envío BPM ─────────────────────────────────────────────────────────
    def send_bpm(self):
        val = self.bpm_spin.value()

        # Serie (igual que antes)
        #self.ser.write(f"{val}\n".encode('utf-8'))

        # BLE (si está conectado)
        if self.ble_client and self.ble_client.is_connected:
            #print(val)
            asyncio.run_coroutine_threadsafe(
                self._ble_send(val), self.loop
            )

    async def _ble_send(self, val):
        try:
            await self.ble_client.write_gatt_char(
                CHAR_UUID, str(val).encode('utf-8'), response=False
            )
        except Exception as e:
            self._set_ble_status(f"error envío: {e}", "red")

    # ── Lectura serie ─────────────────────────────────────────────────────
    def update(self):
        while self.ser.in_waiting:
            try:
                raw   = self.ser.readline().decode('utf-8', errors='ignore').strip()
                value = float(raw)
            except ValueError:
                print(raw)
                continue

            now = QtCore.QTime.currentTime().msecsSinceStartOfDay() / 1000.0
            if self.t0 is None:
                self.t0 = now

            self.data.append(value)
            self.t_data.append(now - self.t0)

        arr = np.array(self.data, dtype=np.float32)
        x   = np.linspace(0, WINDOW_SEC, len(arr))
        self.curve.setData(x, arr)
        self.plot_widget.setXRange(0, WINDOW_SEC, padding=0)

    # ── BPM ───────────────────────────────────────────────────────────────
    def calc_bpm(self):
        arr   = np.array(self.data,   dtype=np.float64)
        t_arr = np.array(self.t_data, dtype=np.float64)

        if len(arr) < 10:
            return

        v_min, v_max = arr.min(), arr.max()
        if (v_max - v_min) < 10:
            return

        dur      = t_arr[-1] - t_arr[0]
        sr_real  = len(t_arr) / dur if dur > 0 else SAMPLE_RATE
        min_dist = max(1, int(0.30 * sr_real))
        height   = v_min + 0.60 * (v_max - v_min)

        peaks, _ = find_peaks(arr, height=height, distance=min_dist)
        if len(peaks) < 2:
            return

        rr_intervals = np.diff(t_arr[peaks])
        rr_valid     = rr_intervals[(rr_intervals > 0.25) & (rr_intervals < 2.0)]
        if len(rr_valid) == 0:
            return

        self.bpm_label.setText(f"BPM: {int(60.0 / rr_valid.mean())}")

    # ── Cierre ────────────────────────────────────────────────────────────
    def closeEvent(self, event):
        self.timer.stop()
        self.bpm_timer.stop()
        if self.ble_client:
            asyncio.run_coroutine_threadsafe(self.ble_client.disconnect(), self.loop)
        if self.ser.is_open:
            self.ser.close()
        self.loop.call_soon_threadsafe(self.loop.stop)
        event.accept()


if __name__ == '__main__':
    app = QtWidgets.QApplication(sys.argv)
    app.setStyle('Fusion')
    win = ECGMonitor()
    win.show()
    sys.exit(app.exec_())