# -*- coding: utf-8 -*-
# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
# Copyright (C) 2017-2018 GEM Foundation
#
# OpenQuake is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# OpenQuake is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with OpenQuake. If not, see <http://www.gnu.org/licenses/>.

# This plugin was forked from https://github.com/alexbruy/qconsolidate
# by Alexander Bruy (alexander.bruy@gmail.com),
# starting from commit 6f27b0b14b925a25c75ea79aea62a0e3d51e30e3.


import os
import configparser

from qgis.PyQt.QtCore import (
                              QUrl,
                              )
from qgis.PyQt.QtGui import (
                             QDesktopServices,
                             QPixmap,
                             QTextDocument,
                             )
from qgis.PyQt.QtWidgets import (
                                 QDialog,
                                 QDialogButtonBox,
                                 QLabel,
                                 QTextBrowser,
                                 QHBoxLayout,
                                 QVBoxLayout,
                                )


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        QDialog.__init__(self, parent)
        self.initGui()

        self.btnHelp = self.buttonBox.button(QDialogButtonBox.StandardButton.Help)

        self.lblLogo.setPixmap(QPixmap(os.path.join(os.path.dirname(__file__), "icons", "qconsolidate.png")))

        cfg = configparser.ConfigParser(interpolation=None)
        cfg.read(os.path.join(os.path.dirname(__file__), "metadata.txt"), encoding="utf-8")
        version = cfg.get("general", "version")

        self.lblVersion.setText(self.tr("Version: %s") % (version))
        doc = QTextDocument()
        doc.setHtml(self.getAboutText())
        self.textBrowser.setDocument(doc)
        self.textBrowser.setOpenExternalLinks(True)

        self.buttonBox.helpRequested.connect(self.openHelp)

        self.btnClose = self.buttonBox.button(QDialogButtonBox.StandardButton.Close)
        self.btnClose.clicked.connect(self.reject)

    def initGui(self):
        self.setWindowTitle('QConsolidate3')
        self.buttonBox = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Close | QDialogButtonBox.StandardButton.Help)
        self.label = QLabel("QConsolidate3")
        self.label.setStyleSheet("font-weight: bold")
        self.lblLogo = QLabel()
        self.lblVersion = QLabel()
        self.textBrowser = QTextBrowser()
        self.h_layout = QHBoxLayout()
        self.h_layout.addWidget(self.lblLogo)
        self.h_layout.addWidget(self.label)
        self.v_layout = QVBoxLayout()
        self.v_layout.addLayout(self.h_layout)
        self.v_layout.addWidget(self.lblVersion)
        self.v_layout.addWidget(self.textBrowser)
        self.v_layout.addWidget(self.buttonBox)
        self.setLayout(self.v_layout)

    def openHelp(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(
            os.path.join(os.path.dirname(__file__), "README.md")))

    def getAboutText(self):
        return self.tr(
            """
            <p>Consolidates all layers from current QGIS project into
            one directory (optionally zipping the whole project in a
            single file).</p>
            <p><strong>Original QConsolidate3</strong>: Danzig</p>
            <p>Fork of the QConsolidate plugin by Alexander Bruy
            and the OQ-Consolidate plugin by the GEM Foundation.</p>
            <p><strong>Version 0.3.0 and later</strong>: updated for
            QGIS 3.44 LTR by Claude, Anthropic's AI assistant (via
            Claude.ai), at the request of Miner-Jeff (GitHub).</p>
            <p>This version is provided as-is and is not actively
            maintained. See the CHANGELOG.md file included with the
            plugin for details of the changes.</p>
            """)
