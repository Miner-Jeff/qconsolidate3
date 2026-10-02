# -*- coding: utf-8 -*-
#
# Copyright (C) 2017-2018 GEM Foundation
#
# OpenQuake is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This plugin was forked from https://github.com/alexbruy/qconsolidate
# by Alexander Bruy (alexander.bruy@gmail.com).

import os

from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction

from . import qconsolidatedialog
from . import aboutdialog

PLUGIN_DIR = os.path.dirname(__file__)
MENU = "QConsolidate3"


def icon(name):
    return QIcon(os.path.join(PLUGIN_DIR, "icons", name))


class QConsolidatePlugin:
    def __init__(self, iface):
        self.iface = iface
        self.dlg = None

    def initGui(self):
        self.actionRun = QAction(icon("qconsolidate.png"), "QConsolidate3",
                                 self.iface.mainWindow())
        self.actionRun.setStatusTip(QCoreApplication.translate(
            "QConsolidate3",
            "Consolidates all layers from current QGIS project into one "
            "directory"))
        self.actionAbout = QAction(icon("about.png"), "About QConsolidate3",
                                   self.iface.mainWindow())

        self.actionRun.triggered.connect(self.run)
        self.actionAbout.triggered.connect(self.about)

        self.iface.addPluginToMenu(MENU, self.actionRun)
        self.iface.addPluginToMenu(MENU, self.actionAbout)
        self.iface.addToolBarIcon(self.actionRun)

    def unload(self):
        self.iface.removePluginMenu(MENU, self.actionRun)
        self.iface.removePluginMenu(MENU, self.actionAbout)
        self.iface.removeToolBarIcon(self.actionRun)

    def run(self):
        self.dlg = qconsolidatedialog.QConsolidateDialog(
            self.iface.mainWindow())
        self.dlg.show()

    def about(self):
        dlg = aboutdialog.AboutDialog(self.iface.mainWindow())
        dlg.exec()
