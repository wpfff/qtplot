import matplotlib.pyplot as plt

from matplotlib.backends.backend_qt4agg import FigureCanvasQTAgg, NavigationToolbar2QT
from PyQt4 import QtGui, QtCore

from util import FixedOrderFormatter
import os


class ExportWidget(QtGui.QWidget):
    def __init__(self, main):
        QtGui.QWidget.__init__(self)

        self.main = main

        self.fig, self.ax = plt.subplots()
        self.cb = None

        self.canvas = FigureCanvasQTAgg(self.fig)
        self.toolbar = NavigationToolbar2QT(self.canvas, self)

        hbox = QtGui.QHBoxLayout()

        self.b_update = QtGui.QPushButton('Update', self)
        self.b_update.clicked.connect(self.on_update)
        hbox.addWidget(self.b_update)

        self.b_copy = QtGui.QPushButton('Copy to clipboard', self)
        self.b_copy.clicked.connect(self.on_copy)
        hbox.addWidget(self.b_copy)

        self.b_export = QtGui.QPushButton('Export...', self)
        self.b_export.clicked.connect(self.on_export)
        hbox.addWidget(self.b_export)

        grid = QtGui.QGridLayout()

        grid.addWidget(QtGui.QLabel('Title'), 1, 1)
        self.le_title = QtGui.QLineEdit('test')
        grid.addWidget(self.le_title, 1, 2)

        grid.addWidget(QtGui.QLabel('Linecut'), 1, 3)
        self.cb_linecut = QtGui.QCheckBox('')
        grid.addWidget(self.cb_linecut, 1, 4)

        grid.addWidget(QtGui.QLabel('Tripcolor'), 1, 5)
        self.cb_tripcolor = QtGui.QCheckBox('')
        grid.addWidget(self.cb_tripcolor, 1, 6)


        grid.addWidget(QtGui.QLabel('X Label'), 2, 1)
        self.le_x_label = QtGui.QLineEdit('test')
        grid.addWidget(self.le_x_label, 2, 2)

        grid.addWidget(QtGui.QLabel('X Format'), 2, 3)
        self.le_x_format = QtGui.QLineEdit('%.0f')
        grid.addWidget(self.le_x_format, 2, 4)

        grid.addWidget(QtGui.QLabel('X Div'), 2, 5)
        self.le_x_div = QtGui.QLineEdit('1e0')
        grid.addWidget(self.le_x_div, 2, 6)


        grid.addWidget(QtGui.QLabel('Y Label'), 3, 1)
        self.le_y_label = QtGui.QLineEdit('test')
        grid.addWidget(self.le_y_label, 3, 2)

        grid.addWidget(QtGui.QLabel('Y Format'), 3, 3)
        self.le_y_format = QtGui.QLineEdit('%.0f')
        grid.addWidget(self.le_y_format, 3, 4)

        grid.addWidget(QtGui.QLabel('Y Div'), 3, 5)
        self.le_y_div = QtGui.QLineEdit('1e0')
        grid.addWidget(self.le_y_div, 3, 6)


        grid.addWidget(QtGui.QLabel('Z Label'), 4, 1)
        self.le_z_label = QtGui.QLineEdit('test')
        grid.addWidget(self.le_z_label, 4, 2)

        grid.addWidget(QtGui.QLabel('Z Format'), 4, 3)
        self.le_z_format = QtGui.QLineEdit('%.0f')
        grid.addWidget(self.le_z_format, 4, 4)

        grid.addWidget(QtGui.QLabel('Z Div'), 4, 5)
        self.le_z_div = QtGui.QLineEdit('1e0')
        grid.addWidget(self.le_z_div, 4, 6)


        grid.addWidget(QtGui.QLabel('Font'), 5, 1)
        self.le_font = QtGui.QLineEdit('Vera Sans')
        grid.addWidget(self.le_font, 5, 2)

        grid.addWidget(QtGui.QLabel('Font size'), 6, 1)
        self.le_font_size = QtGui.QLineEdit('12')
        grid.addWidget(self.le_font_size, 6, 2)


        grid.addWidget(QtGui.QLabel('Width'), 5, 3)
        self.le_width = QtGui.QLineEdit('3')
        grid.addWidget(self.le_width, 5, 4)

        grid.addWidget(QtGui.QLabel('Height'), 6, 3)
        self.le_height = QtGui.QLineEdit('3')
        grid.addWidget(self.le_height, 6, 4)


        grid.addWidget(QtGui.QLabel('CB Orient'), 5, 5)
        self.cb_cb_orient = QtGui.QComboBox()
        self.cb_cb_orient.addItems(['vertical', 'horizontal'])
        grid.addWidget(self.cb_cb_orient, 5, 6)

        grid.addWidget(QtGui.QLabel('CB Pos'), 6, 5)
        self.le_cb_pos = QtGui.QLineEdit('0 0 1 1')
        grid.addWidget(self.le_cb_pos, 6, 6)

        grid.addWidget(QtGui.QLabel('Rasterize'), 7, 1)
        self.cb_rasterize = QtGui.QCheckBox('')
        grid.addWidget(self.cb_rasterize, 7, 2)

        grid.addWidget(QtGui.QLabel('DPI'), 7, 3)
        self.le_dpi = QtGui.QLineEdit('80')
        grid.addWidget(self.le_dpi, 7, 4)

        vbox = QtGui.QVBoxLayout(self)
        vbox.addWidget(self.toolbar)
        vbox.addWidget(self.canvas)
        vbox.addLayout(hbox)
        vbox.addLayout(grid)

    def set_info(self, title, x, y, z):
        self.le_title.setText(title)
        self.le_x_label.setText(x)
        self.le_y_label.setText(y)
        self.le_z_label.setText(z)

    def keyPressEvent(self, e):
        if e.key() == QtCore.Qt.Key_Return:
            self.on_update()

    def on_update(self):
        if self.main.data is not None:
            self.ax.clear()

            x, y, z = self.main.data.get_pcolor()

            cmap = self.main.canvas.colormap.get_mpl_colormap()

            if self.cb_tripcolor.checkState() != QtCore.Qt.Checked:
                quadmesh = self.ax.pcolormesh(x, y, z, cmap=cmap, rasterized=True)
                quadmesh.set_clim(self.main.canvas.colormap.get_limits())
            else:
                quadmesh = self.ax.tripcolor(self.main.data.x.ravel(),
                                             self.main.data.y.ravel(),
                                             self.main.data.z.ravel(),
                                             cmap=cmap, rasterized=True)

                quadmesh.set_clim(self.main.canvas.colormap.get_limits())

            self.ax.axis('tight')

            self.ax.set_title(self.le_title.text())
            self.ax.set_xlabel(self.le_x_label.text())
            self.ax.set_ylabel(self.le_y_label.text())

            self.ax.xaxis.set_major_formatter(FixedOrderFormatter(
                str(self.le_x_format.text()), float(self.le_x_div.text())))
            self.ax.yaxis.set_major_formatter(FixedOrderFormatter(
                str(self.le_y_format.text()), float(self.le_y_div.text())))

            if self.cb is not None:
                self.cb.remove()

            self.cb = self.fig.colorbar(quadmesh,
                                        orientation=str(self.cb_cb_orient.currentText()))

            self.cb.formatter = FixedOrderFormatter(
                str(self.le_z_format.text()), float(self.le_z_div.text()))

            self.cb.update_ticks()

            self.cb.set_label(self.le_z_label.text())
            self.cb.draw_all()

            if self.cb_linecut.checkState() == QtCore.Qt.Checked:
                for linetrace in self.main.linecut.linetraces:
                    if linetrace.type == 'horizontal':
                        plt.axhline(linetrace.position, color='red')
                    elif linetrace.type == 'vertical':
                        plt.axvline(linetrace.position, color='red')

            self.fig.tight_layout()

            self.canvas.draw()

    def on_copy(self):
        path = os.path.dirname(os.path.realpath(__file__))
        path = os.path.join(path, 'test.png')
        self.fig.savefig(path)

        img = QtGui.QImage(path)
        QtGui.QApplication.clipboard().setImage(img)

    def on_export(self):
        path = os.path.dirname(os.path.realpath(__file__))
        filename = QtGui.QFileDialog.getSaveFileName(self,
                                                     'Export figure',
                                                     path,
                                                     'Portable Network Graphics (*.png);;Portable Document Format (*.pdf);;Postscript (*.ps);;Encapsulated Postscript (*.eps);;Scalable Vector Graphics (*.svg)')
        filename = str(filename)

        if filename != '':
            previous_size = self.fig.get_size_inches()
            self.fig.set_size_inches(float(self.le_width.text()),
                                     float(self.le_height.text()))

            dpi = int(self.le_dpi.text())

            self.fig.savefig(filename, dpi=dpi, bbox_inches='tight')
            self.fig.set_size_inches(previous_size)

            self.canvas.draw()
