import os
from PyQt4 import QtCore, QtGui, uic


class Settings(QtGui.QDialog):
    def __init__(self, parent, model):
        super(Settings, self).__init__(parent)

        self.model = model

        directory = os.path.dirname(os.path.realpath(__file__))
        path = os.path.join(directory, 'ui/settings.ui')
        uic.loadUi(path, self)

    def show_window(self):
        self.show()
        self.raise_()

    def closeEvent(self, event):
        self.hide()
        event.ignore()
