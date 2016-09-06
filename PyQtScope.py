#!/usr/bin/env python

# Control program for the Tektronix TDS2022B oscilloscope
# Copyright (C) 2016  Pavel Demin
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import os
import sys
import struct

import usb.core
import usb.util
import usb.backend.libusb1

import numpy as np

import matplotlib
matplotlib.use('Qt5Agg')
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure
from matplotlib.ticker import Formatter, FuncFormatter

from PyQt5.uic import loadUiType
from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication, QMainWindow, QMenu, QVBoxLayout, QSizePolicy, QMessageBox, QWidget, QDialog, QFileDialog

Ui_PyQtScope, QMainWindow = loadUiType('PyQtScope.ui')

def metric_prefix(x, pos = None):
  if x == 0.0:
    return '0'
  elif abs(x) >= 1.0e6:
    return '%gM' % (x * 1.0e-6)
  elif abs(x) >= 1.0e3:
    return '%gk' % (x * 1.0e-3)
  elif abs(x) >= 1.0e0:
    return '%g' % x
  elif abs(x) >= 1.0e-3:
    return '%gm' % (x * 1e+3)
  elif abs(x) >= 1.0e-6:
    return '%gu' % (x * 1e+6)
  else:
    return '%g' % x


class PyQtScope(QMainWindow, Ui_PyQtScope):
  def __init__(self):
    super(PyQtScope, self).__init__()
    self.setupUi(self)
    # data buffers
    self.buffer1 = bytearray(2500)
    self.buffer2 = bytearray(2500)
    self.data1 = np.frombuffer(self.buffer1, np.int8)
    self.data2 = np.frombuffer(self.buffer2, np.int8)
    # create figure
    figure = Figure()
    figure.set_facecolor('none')
    figure.subplots_adjust(left = 0.01, bottom = 0.01, right = 0.99, top = 0.99)
    self.axes = figure.add_subplot(111)
    self.canvas = FigureCanvas(figure)
    self.plotLayout.addWidget(self.canvas)
    self.curve1, = self.axes.plot(np.zeros(2500), color = '#EEDD00')
    self.curve2, = self.axes.plot(np.zeros(2500), color = '#00DDEE')
    self.axes.set_xticks(np.arange(0, 2501, 250))
    self.axes.set_yticks(np.arange(-100, 101, 25))
    self.axes.set_xticklabels([])
    self.axes.set_yticklabels([])
    self.axes.grid()
    # create navigation toolbar
    self.toolbar = NavigationToolbar(self.canvas, self.plotWidget, False)
    # remove subplots action
    actions = self.toolbar.actions()
    self.toolbar.removeAction(actions[7])
    self.plotLayout.addWidget(self.toolbar)
    # connect signals from buttons and boxes
    self.readButton.clicked.connect(self.read_data)
    self.saveButton.clicked.connect(self.save_data)
    # setup USB connection
    self.btag = 0
    if os.name == 'nt':
      backend = usb.backend.libusb1.get_backend(find_library = lambda x: 'libusb-1.0.dll')
    else:
      backend = usb.backend.libusb1.get_backend()
    self.device = usb.core.find(idVendor = 0x0699, idProduct = 0x0369, backend = backend)
    while self.device  is None:
      reply = QMessageBox.critical(self, 'PyQtScope', 'Cannot access USB device', QMessageBox.Abort | QMessageBox.Retry | QMessageBox.Ignore)
      if reply == QMessageBox.Abort:
        sys.exit(1)
      elif reply == QMessageBox.Retry:
        self.device = usb.core.find(idVendor = 0x0699, idProduct = 0x0369, backend = backend)
      else:
        break
    if self.device:
      self.device.set_configuration()
      self.transmit_command(b'*IDN?')
      print(self.receive_result())
      self.transmit_command(b'DESE 1')
      self.transmit_command(b'*ESE 1')
      self.transmit_command(b'*SRE 32')
      self.transmit_command(b'DAT INIT')

  def transmit_command(self, command):
    size = len(command)
    self.btag = (self.btag % 255) + 1
    data = struct.pack('BBBx', 1, self.btag, ~self.btag & 0xFF)
    data += struct.pack('<LBxxx', size, 1)
    data += command + b'\0'*((4 - (size % 4)) % 4)
    self.device.write(0x06, data, 1000)

  def receive_result(self):
    result = b''
    stop = 0
    while not stop:
      self.btag = (self.btag % 255) + 1
      data = struct.pack('BBBx', 2, self.btag, ~self.btag & 0xFF)
      data += struct.pack('<LBxxx', 1024, 0)
      self.device.write(0x06, data, 1000)
      data = self.device.read(0x85, 1036, 1000).tobytes()
      size, stop = struct.unpack_from('<LBxxx', data, 4)
      result += data[12:size+12]
    return result

  def read_data(self):
    if not self.device: return
    self.transmit_command(b'DAT:SOU CH1;:CURV?')
    self.buffer1[:] = self.receive_result()[6:-1]
    self.curve1.set_ydata(self.data1)
    self.transmit_command(b'DAT:SOU CH2;:CURV?')
    self.buffer2[:] = self.receive_result()[6:-1]
    self.curve2.set_ydata(self.data2)
    self.canvas.draw()

  def save_data(self):
    dialog = QFileDialog(self, 'Write csv file', '.', '*.csv')
    dialog.setDefaultSuffix('csv')
    dialog.setAcceptMode(QFileDialog.AcceptSave)
    dialog.setOptions(QFileDialog.DontConfirmOverwrite)
    if dialog.exec() == QDialog.Accepted:
      name = dialog.selectedFiles()
      fh = open(name[0], 'w')
      fh.write('time;ch1;ch2\n')
      for i in range(0, 2500):
        fh.write('%12.9f;%12.9f;%12.9f\n' % (i, self.data1[i], self.data2[i]))
      fh.close()

app = QApplication(sys.argv)
window = PyQtScope()
window.show()
sys.exit(app.exec_())
