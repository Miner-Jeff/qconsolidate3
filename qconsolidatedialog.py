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
import re
import shutil
import zipfile

from qgis.PyQt.QtCore import QDir, QFileInfo, QSettings
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from qgis.core import QgsApplication, QgsProject, QgsTask
from qgis.utils import iface

from .consolidatethread import (ConsolidateTask, MODE_KEEP, MODE_GPKG,
                                MODE_SHP)
from .utils import log_msg, tr

MODES = [
    (MODE_KEEP, 'Keep original formats (copy files)'),
    (MODE_GPKG, 'Convert all to GeoPackage'),
    (MODE_SHP, 'Convert all to Shapefile'),
]
# values stored by 0.3.0
OLD_MODE_VALUES = {'GeoPackage': MODE_GPKG, 'SHP': MODE_SHP}

YES = QMessageBox.StandardButton.Yes
NO = QMessageBox.StandardButton.No


class QConsolidateDialog(QDialog):
    def __init__(self, parent=None):
        QDialog.__init__(self, parent)
        self.initGui()
        self.consolidateTask = None

        self.btnOk = self.buttonBox.button(QDialogButtonBox.StandardButton.Ok)
        self.btnCancel = self.buttonBox.button(
            QDialogButtonBox.StandardButton.Cancel)
        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)

        self.project_name_le.editingFinished.connect(
            self.on_project_name_editing_finished)
        self.project_name_le.textChanged.connect(self.set_ok_button)
        self.leOutputDir.textChanged.connect(self.set_ok_button)
        self.btnBrowse.clicked.connect(self.setOutDirectory)

        project_name = QFileInfo(QgsProject.instance().fileName()).baseName()
        if project_name:
            self.project_name_le.setText(get_valid_filename(project_name))
        self.set_ok_button()

    def initGui(self):
        self.setWindowTitle('QConsolidate3')
        s = QSettings()
        self.project_name_lbl = QLabel('Project name')
        self.project_name_le = QLineEdit()
        self.checkBoxZip = QCheckBox('Also create a Zip file')
        self.checkBoxZip.setChecked(
            s.value("qconsolidate3/zip", False, type=bool))
        self.formatLbl = QLabel('Vector layers')
        self.cb = QComboBox()
        for mode, label in MODES:
            self.cb.addItem(label, mode)
        saved = s.value("qconsolidate3/mode", "") or OLD_MODE_VALUES.get(
            s.value("qconsolidate3/format", ""), MODE_KEEP)
        idx = self.cb.findData(saved)
        self.cb.setCurrentIndex(idx if idx >= 0 else 0)
        self.cb.setToolTip(
            "Keep original formats: files are copied as they are, once per "
            "file, even if several layers use them. Layers without a file "
            "(scratch, PostGIS, WFS...) and layers that would drag along a "
            "large file the project mostly does not use are exported to "
            "GeoPackage instead.\n\nConvert: every vector layer is "
            "rewritten as its own GeoPackage or Shapefile.")

        self.label = QLabel("Output directory")
        self.leOutputDir = QLineEdit()
        self.leOutputDir.setText(s.value("qconsolidate3/lastdir", ""))
        self.btnBrowse = QPushButton("Browse...")
        self.buttonBox = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel)

        self.v_layout = QVBoxLayout()
        self.setLayout(self.v_layout)
        h = QHBoxLayout()
        h.addWidget(self.project_name_lbl)
        h.addWidget(self.project_name_le)
        self.v_layout.addLayout(h)
        h = QHBoxLayout()
        h.addWidget(self.label)
        h.addWidget(self.leOutputDir)
        h.addWidget(self.btnBrowse)
        self.v_layout.addLayout(h)
        h = QHBoxLayout()
        h.addWidget(self.formatLbl)
        h.addWidget(self.cb)
        self.v_layout.addLayout(h)
        self.v_layout.addWidget(self.checkBoxZip)
        self.v_layout.addWidget(self.buttonBox)

    def on_project_name_editing_finished(self):
        self.project_name_le.setText(
            get_valid_filename(self.project_name_le.text()))
        self.set_ok_button()

    def set_ok_button(self):
        self.btnOk.setEnabled(bool(self.project_name_le.text().strip()) and
                              bool(self.leOutputDir.text().strip()))

    def setOutDirectory(self):
        s = QSettings()
        lastdir = s.value("qconsolidate3/lastdir", "")
        outDir = QFileDialog.getExistingDirectory(
            self, self.tr("Select output directory"), lastdir)
        if outDir:
            s.setValue("qconsolidate3/lastdir", outDir)
            self.leOutputDir.setText(outDir)

    def fail(self, msg):
        log_msg(tr(msg), level='C', message_bar=iface.messageBar())
        QMessageBox.warning(self, 'QConsolidate3', tr(msg))

    def accept(self):
        project = QgsProject.instance()
        projectFile = project.fileName()

        # The consolidated project is built from the SAVED project file, so
        # it must exist on disk and match what is on screen.
        if not projectFile or not os.path.isfile(projectFile):
            self.fail("Please save the project to a .qgs or .qgz file "
                      "first.")
            return
        if project.isDirty():
            res = QMessageBox.question(
                self, "Unsaved changes",
                "The project has unsaved changes. Save it now before "
                "consolidating?", YES | NO)
            if res != YES or not project.write():
                self.fail("Consolidation needs the project to be saved "
                          "first.")
                return

        project_name = get_valid_filename(self.project_name_le.text())
        project_name = re.sub(r'\.(qgs|qgz)$', '', project_name,
                              flags=re.I)
        if not project_name:
            self.fail("Please specify the project name.")
            return
        baseDir = self.leOutputDir.text().strip()
        if not baseDir:
            self.fail("Please specify the output directory.")
            return
        outputDir = os.path.join(baseDir, project_name)

        srcDir = os.path.normcase(os.path.abspath(
            os.path.dirname(projectFile)))
        if os.path.normcase(os.path.abspath(outputDir)) == srcDir:
            self.fail("The output folder is the folder the current project "
                      "is in. Choose a different output directory.")
            return

        d = QDir(outputDir)
        if not d.exists() and not d.mkpath("."):
            self.fail("Can't create directory to store the project.")
            return
        if d.exists("layers"):
            res = QMessageBox.question(
                self, "Directory exists",
                "Output directory already contains a 'layers' subdirectory. "
                "Maybe this directory was used to consolidate another "
                "project. Files with the same names will be overwritten. "
                "Continue?", YES | NO)
            if res != YES:
                return

        s = QSettings()
        s.setValue("qconsolidate3/lastdir", baseDir)
        s.setValue("qconsolidate3/mode", self.cb.currentData())
        s.setValue("qconsolidate3/zip", self.checkBoxZip.isChecked())

        newProjectFile = os.path.join(outputDir, '%s.qgs' % project_name)
        newQgd = os.path.join(outputDir, '%s.qgd' % project_name)
        extra = []
        try:
            if projectFile.lower().endswith('.qgz'):
                with zipfile.ZipFile(projectFile) as z:
                    for member in z.namelist():
                        low = member.lower()
                        if low.endswith('.qgs'):
                            dest = newProjectFile
                        elif low.endswith('.qgd'):
                            dest = newQgd
                        elif not os.path.basename(member):
                            continue  # directory entry
                        else:
                            dest = os.path.join(outputDir,
                                                os.path.basename(member))
                            extra.append(dest)
                        with z.open(member) as src, open(dest, 'wb') as out:
                            shutil.copyfileobj(src, out)
            elif projectFile.lower().endswith('.qgs'):
                shutil.copyfile(projectFile, newProjectFile)
                oldQgd = os.path.splitext(projectFile)[0] + '.qgd'
                if os.path.isfile(oldQgd):
                    shutil.copyfile(oldQgd, newQgd)
            else:
                raise IOError('Unknown project file type: ' + projectFile)
        except Exception as exc:
            log_msg(str(exc), level='C', message_bar=iface.messageBar(),
                    exception=exc)
            return
        if os.path.isfile(newQgd):
            extra.append(newQgd)

        self.consolidateTask = ConsolidateTask(
            'QConsolidate3', QgsTask.Flag.CanCancel, outputDir,
            newProjectFile, self.checkBoxZip.isChecked(),
            self.cb.currentData(), extra,
            s.value("qconsolidate3/copy_threshold_mb", 100, type=float))
        self.consolidateTask.begun.connect(self.on_consolidation_begun)
        QgsApplication.taskManager().addTask(self.consolidateTask)
        super().accept()

    def on_consolidation_begun(self):
        log_msg("Consolidation started.", level='I', duration=4,
                message_bar=iface.messageBar())


# from https://github.com/django/django/blob/master/django/utils/text.py#L223
def get_valid_filename(s):
    """
    Return the given string converted to a string that can be used for a clean
    filename. Remove leading and trailing spaces; convert other spaces to
    underscores; and remove anything that is not an alphanumeric, dash,
    underscore, or dot.
    >>> get_valid_filename("john's portrait in 2004.jpg")
    'johns_portrait_in_2004.jpg'
    """
    s = str(s).strip().replace(' ', '_')
    return re.sub(r'(?u)[^-\w.]', '', s)
