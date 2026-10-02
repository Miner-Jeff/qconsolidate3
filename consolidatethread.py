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
#
# 0.3.0 / 0.4.0 changes:
#   * project layers are only touched on the main thread (in __init__);
#     the background task works from QgsVectorLayerFeatureSource objects
#     and plain strings, which are thread safe;
#   * source data is never modified;
#   * "Keep original formats" mode copies files as they are, once per
#     source file, with all side-car files, and converts only layers that
#     have no file (memory, database, web) or would drag along a large
#     file the project mostly does not use;
#   * layers that cannot be consolidated are skipped, not fatal.

import os
import re
import shutil
import zipfile

from qgis.PyQt.QtCore import QIODevice, QFile
from qgis.PyQt.QtXml import QDomDocument

from qgis.core import (
    QgsFeature,
    QgsFields,
    QgsPathResolver,
    QgsProject,
    QgsProviderRegistry,
    QgsRasterLayer,
    QgsReadWriteContext,
    QgsTask,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsVectorLayerFeatureSource,
)

from osgeo import gdal

from .utils import log_msg

try:
    from qgis.utils import iface
except ImportError:  # running outside the QGIS desktop (tests)
    iface = None


MODE_KEEP = 'keep'
MODE_GPKG = 'gpkg'
MODE_SHP = 'shp'

# vector providers whose data lives in a local file we can copy as-is
COPY_PROVIDERS = ('ogr', 'delimitedtext')
SHP_EXTS = ('.shp', '.shx', '.dbf', '.prj', '.cpg', '.qix', '.qpj')


class TaskCanceled(Exception):
    pass


def _enum(owner, scoped, member):
    """Return owner.scoped.member, falling back to owner.member."""
    holder = getattr(owner, scoped, owner)
    return getattr(holder, member, getattr(owner, member, None))


ORIGIN_PROVIDER = _enum(QgsFields, 'FieldOrigin', 'OriginProvider')
ORIGIN_EDIT = _enum(QgsFields, 'FieldOrigin', 'OriginEdit')
WRITER_NO_ERROR = _enum(QgsVectorFileWriter, 'WriterError', 'NoError')


def sanitize(name):
    base = re.sub(r'[\\/:*?"<>|\x00-\x1f]', '_', name or '').strip(' .')
    return base or 'layer'


def norm(path):
    return os.path.normcase(os.path.abspath(path))


def is_copyable_path(path):
    if not path:
        return False
    if os.path.isfile(path):
        return True
    # File Geodatabases are folders
    return os.path.isdir(path) and path.rstrip('/\\').lower().endswith('.gdb')


def path_size(path):
    if os.path.isfile(path):
        return os.path.getsize(path)
    total = 0
    for dirpath, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(dirpath, f))
            except OSError:
                pass
    return total


class ConsolidateTask(QgsTask):

    def __init__(self, description, flags, outputDir, projectFile,
                 saveToZip, mode, extraFiles=None, copyThresholdMB=100):
        super().__init__(description, flags)
        self.outputDir = outputDir
        self.layersDir = os.path.join(outputDir, "layers")
        self.projectFile = projectFile
        self.saveToZip = saveToZip
        self.mode = mode if mode in (MODE_KEEP, MODE_GPKG, MODE_SHP) \
            else MODE_GPKG
        self.extraFiles = list(extraFiles or [])
        self.threshold = max(0, float(copyThresholdMB)) * 1024 * 1024
        self.exception = None
        self.skipped = []      # (layer name, reason)
        self.notes = []        # informational lines for the log
        self.copiedLayers = 0
        self.convertedLayers = 0
        self.transformContext = QgsProject.instance().transformContext()
        self.registry = QgsProviderRegistry.instance()

        # ---- collect everything we need from layers on the MAIN thread ----
        self.jobs = []
        # sources (absolute) of layers that stay where they are, so that
        # switching the project to relative paths cannot re-point them
        self.keepSources = {}
        for layer in QgsProject.instance().mapLayers().values():
            name = layer.name()
            self.keepSources[layer.id()] = layer.source()
            if not layer.isValid():
                self.skipped.append((name, 'layer is invalid / source missing'))
                continue
            if isinstance(layer, QgsVectorLayer):
                self.jobs.append(self._vectorJob(layer))
            elif isinstance(layer, QgsRasterLayer):
                job = self._rasterJob(layer)
                if job:
                    self.jobs.append(job)
            else:
                self.skipped.append(
                    (name, 'layer type not supported, left pointing at '
                           'original source'))

        self.setDependentLayers(QgsProject.instance().mapLayers().values())

    # ------------------------------------------------------------------ jobs
    def _vectorJob(self, layer):
        layerFields = layer.fields()
        keep = [i for i in range(layerFields.count())
                if layerFields.fieldOrigin(i) in (ORIGIN_PROVIDER, ORIGIN_EDIT)]
        outFields = QgsFields()
        for i in keep:
            outFields.append(layerFields.at(i))
        storage = ''
        try:
            storage = layer.dataProvider().storageType() or ''
        except Exception:
            pass

        provider = layer.providerType()
        parts, copyPath = None, None
        if provider in COPY_PROVIDERS:
            try:
                parts = self.registry.decodeUri(provider, layer.source())
            except Exception:
                parts = None
            if parts and is_copyable_path(parts.get('path')):
                copyPath = parts['path']

        return {
            'kind': 'vector',
            'id': layer.id(),
            'name': layer.name(),
            'provider': provider,
            'parts': parts,
            'copyPath': copyPath,
            'subLayer': (parts or {}).get('layerName') or
                        (parts or {}).get('layerId') or '',
            'modified': layer.isEditable() and layer.isModified(),
            'source': QgsVectorLayerFeatureSource(layer),
            'keep': keep,
            'fields': outFields,
            'wkb': layer.wkbType(),
            'crs': layer.crs(),
            'count': max(layer.featureCount(), 1),
            'fromGpkg': 'GPKG' in storage.upper(),
        }

    def _rasterJob(self, layer):
        if layer.providerType() != 'gdal':
            self.skipped.append(
                (layer.name(), 'web/database raster (%s), left pointing at '
                               'original source' % layer.providerType()))
            return None
        parts = self.registry.decodeUri('gdal', layer.source())
        path = parts.get('path') or ''
        if not is_copyable_path(path):
            self.skipped.append(
                (layer.name(), 'raster is not a local file, left pointing at '
                               'original source'))
            return None
        return {'kind': 'raster', 'id': layer.id(), 'name': layer.name(),
                'provider': 'gdal', 'parts': parts, 'copyPath': path}

    # ------------------------------------------------------------- QgsTask
    def run(self):
        try:
            self.consolidate()
        except Exception as exc:
            self.exception = exc
            return False
        return True

    def finished(self, success):
        bar = iface.messageBar() if iface is not None else None
        for line in self.notes:
            log_msg('Note: ' + line, level='W')
        for name, reason in self.skipped:
            log_msg('Layer "%s" not consolidated: %s' % (name, reason),
                    level='W')
        if success:
            done = []
            if self.copiedLayers:
                done.append('%d copied in original format' % self.copiedLayers)
            if self.convertedLayers:
                done.append('%d converted' % self.convertedLayers)
            msg = 'Consolidation complete: %s.' % (
                ', '.join(done) if done else 'no layers copied')
            if self.skipped:
                msg += (' %d layer(s) were left pointing at their original '
                        'source; see the QConsolidate3 tab in Log Messages.'
                        % len(self.skipped))
                log_msg(msg, level='W', message_bar=bar)
            else:
                log_msg(msg, level='S', message_bar=bar)
        elif self.exception is not None:
            level = 'W' if isinstance(self.exception, TaskCanceled) else 'C'
            log_msg(str(self.exception), level=level, message_bar=bar,
                    exception=self.exception)

    def checkCanceled(self):
        if self.isCanceled():
            raise TaskCanceled('Consolidation canceled')

    # ------------------------------------------------------------- planning
    def plan(self):
        """Split jobs into whole-file copies and per-layer conversions."""
        groups = {}
        conversions = []
        for job in self.jobs:
            if job['kind'] == 'raster':
                use_copy = True
            elif self.mode != MODE_KEEP or not job['copyPath']:
                use_copy = False
            elif job['modified']:
                use_copy = False
                self.notes.append(
                    '"%s" has unsaved edits, so it was exported to '
                    'GeoPackage (including the edits) instead of copying '
                    'the file.' % job['name'])
            else:
                use_copy = True
            if use_copy:
                g = groups.setdefault(norm(job['copyPath']), {
                    'path': job['copyPath'], 'vectors': [], 'rasters': []})
                g['vectors' if job['kind'] == 'vector' else 'rasters'] \
                    .append(job)
            else:
                conversions.append(job)

        copies = []
        for g in groups.values():
            big = self.tooBigToCopy(g)
            if big:
                conversions.extend(g['vectors'])
                size, total, used = big
                self.notes.append(
                    '%s is %.1f MB and contains %d layers, but the project '
                    'uses %d. Only the used layer(s) were exported, instead '
                    'of copying the whole file.' % (
                        os.path.basename(g['path']), size / 1048576.0,
                        total, used))
            else:
                copies.append(g)
        return copies, conversions

    def tooBigToCopy(self, g):
        if g['rasters'] or not g['vectors']:
            return None  # rasters can only be copied whole
        size = path_size(g['path'])
        if size <= self.threshold:
            return None
        total = self.countLayers(g['path'])
        used = len({j['subLayer'] for j in g['vectors']})
        if total and total > used:
            return size, total, used
        return None

    @staticmethod
    def countLayers(path):
        gdal.PushErrorHandler('CPLQuietErrorHandler')
        try:
            total = 0
            ds = gdal.OpenEx(path, gdal.OF_VECTOR)
            if ds is not None:
                total += ds.GetLayerCount()
            ds = gdal.OpenEx(path, gdal.OF_RASTER)
            if ds is not None:
                subs = ds.GetSubDatasets()
                total += len(subs) if subs else (1 if ds.RasterCount else 0)
            ds = None
            return total
        except Exception:
            return None
        finally:
            gdal.PopErrorHandler()

    @staticmethod
    def fileList(path):
        """The file plus every side-car file GDAL knows belongs to it."""
        if os.path.isdir(path):
            return [path]
        files = [path]
        gdal.PushErrorHandler('CPLQuietErrorHandler')
        try:
            ds = gdal.OpenEx(path, gdal.OF_VECTOR | gdal.OF_RASTER)
            extra = ds.GetFileList() if ds is not None else None
            ds = None
        except Exception:
            extra = None
        finally:
            gdal.PopErrorHandler()
        for f in extra or []:
            if os.path.isfile(f) and norm(f) not in map(norm, files):
                files.append(f)
        # recent edits to GeoPackage/SQLite files can still be in the WAL
        if os.path.isfile(path + '-wal'):
            files.append(path + '-wal')
        return files

    def reserve(self, names):
        """True and reserve if none of the top-level names are taken."""
        low = {n.lower() for n in names}
        if low & self.usedNames:
            return False
        self.usedNames |= low
        return True

    # --------------------------------------------------------------- work
    def consolidate(self):
        gdal.AllRegister()
        os.makedirs(self.layersDir, exist_ok=True)
        self.usedNames = set()
        self.ctx = QgsReadWriteContext()
        self.ctx.setPathResolver(QgsPathResolver(self.projectFile))

        doc = self.loadProject()
        root = doc.documentElement()
        self.makePathsRelative(doc, root)
        projectLayers = root.firstChildElement("projectlayers")

        outFiles = [self.projectFile] + [f for f in self.extraFiles
                                         if os.path.isfile(f)]
        self.setProgress(1.0)
        copies, conversions = self.plan()
        total = max(len(copies) + len(conversions), 1)
        step = 0
        self.checkCanceled()

        for g in copies:
            layerJobs = g['vectors'] + g['rasters']
            try:
                files, destMain = self.copyGroup(g)
            except TaskCanceled:
                raise
            except Exception as exc:
                for job in layerJobs:
                    self.skipped.append((job['name'], 'copy failed: %s' % exc))
                continue
            outFiles.extend(files)
            for job in layerJobs:
                parts = dict(job['parts'])
                parts['path'] = destMain
                uri = self.relative(job['provider'], parts)
                if self.updateLayer(doc, projectLayers, job['id'], uri,
                                    job['provider'], None):
                    self.keepSources.pop(job['id'], None)
                    self.copiedLayers += 1
                else:
                    self.skipped.append(
                        (job['name'], 'not found in the saved project file'))
            step += 1
            self.setProgress(step / total * 95)
            self.checkCanceled()

        for job in conversions:
            try:
                files, uri = self.writeVector(job, step, total)
            except TaskCanceled:
                raise
            except Exception as exc:
                self.skipped.append((job['name'], 'export failed: %s' % exc))
                continue
            if not self.updateLayer(doc, projectLayers, job['id'], uri,
                                    'ogr', 'UTF-8'):
                self.skipped.append(
                    (job['name'], 'not found in the saved project file'))
                continue
            outFiles.extend(files)
            self.keepSources.pop(job['id'], None)
            self.convertedLayers += 1
            step += 1
            self.setProgress(step / total * 95)
            self.checkCanceled()

        self.pinUnconsolidated(doc, projectLayers)
        self.saveProject(doc)

        if self.saveToZip:
            self.zipfiles(outFiles, os.path.splitext(self.projectFile)[0])
        self.setProgress(100)
        return True

    def relative(self, provider, parts):
        uri = self.registry.encodeUri(provider, parts)
        try:
            return self.registry.absoluteToRelativeUri(provider, uri,
                                                       self.ctx)
        except Exception:
            return uri

    def copyGroup(self, g):
        src = os.path.abspath(g['path'])
        srcDir = os.path.dirname(src)
        items = []
        for f in self.fileList(src):
            absF = os.path.abspath(f)
            rel = os.path.relpath(absF, srcDir)
            if rel.startswith('..'):
                rel = os.path.basename(absF)
            items.append((absF, rel))
        tops = {rel.split(os.sep)[0] for _, rel in items}

        # keep original file names; if another source file with the same
        # name was already copied, put this one in its own sub-folder
        sub = ''
        if not self.reserve(tops):
            stem = sanitize(os.path.splitext(os.path.basename(src))[0])
            n = 2
            while not self.reserve(['%s_%d' % (stem, n)]):
                n += 1
            sub = '%s_%d' % (stem, n)
        destDir = os.path.join(self.layersDir, sub)
        os.makedirs(destDir, exist_ok=True)

        copied = []
        for absF, rel in items:
            dest = os.path.join(destDir, rel)
            if os.path.isdir(absF):
                shutil.copytree(absF, dest, dirs_exist_ok=True)
                for dirpath, _, fs in os.walk(dest):
                    copied.extend(os.path.join(dirpath, x) for x in fs)
            else:
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                shutil.copy2(absF, dest)
                copied.append(dest)
            self.checkCanceled()
        return copied, os.path.join(destDir, os.path.basename(src))

    def writeVector(self, job, step, total):
        shp = self.mode == MODE_SHP
        if shp:
            driver, ext, exts = 'ESRI Shapefile', 'shp', SHP_EXTS
        else:
            driver, ext, exts = 'GPKG', 'gpkg', ('.gpkg',)
        base = sanitize(job['name'])
        candidate, n = base, 2
        while not self.reserve([candidate + e for e in exts]):
            candidate = '%s_%d' % (base, n)
            n += 1
        fileBase = candidate
        outFile = os.path.join(self.layersDir, '%s.%s' % (fileBase, ext))
        if os.path.exists(outFile):
            if shp:
                QgsVectorFileWriter.deleteShapeFile(outFile)
            else:
                os.remove(outFile)

        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = driver
        options.fileEncoding = 'UTF-8'
        # GeoPackage reserves table names starting with gpkg / sqlite_ /
        # rtree_; the file can keep the layer's name, the table cannot
        tableName = fileBase
        if not shp and re.match(r'(?i)^(gpkg|sqlite_|rtree_)', tableName):
            tableName = 'layer_' + tableName
        options.layerName = tableName
        if not shp:
            # GeoPackage needs an integer primary key column. If the data
            # already has a column called "fid" that is not the GeoPackage
            # key of the source, keep it as an ordinary column and give the
            # primary key another name, instead of deleting user data.
            names = [f.name().lower() for f in job['fields']]
            if 'fid' in names and not job['fromGpkg']:
                pk, i = 'fid_pk', 2
                while pk in names:
                    pk = 'fid_pk%d' % i
                    i += 1
                options.layerOptions = ['FID=%s' % pk]

        writer = QgsVectorFileWriter.create(
            outFile, job['fields'], job['wkb'], job['crs'],
            self.transformContext, options)
        if writer is None or writer.hasError() != WRITER_NO_ERROR:
            msg = writer.errorMessage() if writer is not None else ''
            raise IOError('cannot create %s: %s' % (outFile, msg))

        keep, outFields = job['keep'], job['fields']
        failed = written = 0
        for i, feat in enumerate(job['source'].getFeatures()):
            out = QgsFeature(outFields)
            out.setGeometry(feat.geometry())
            attrs = feat.attributes()
            out.setAttributes([attrs[k] for k in keep])
            if writer.addFeature(out):
                written += 1
            else:
                failed += 1
            if i % 500 == 0:
                self.checkCanceled()
                self.setProgress(
                    (step + min(i / job['count'], 1)) / total * 95)
        err = writer.errorMessage()
        del writer  # flushes and closes the file

        if failed:
            raise IOError('%d of %d features could not be written (%s)'
                          % (failed, failed + written, err))

        if shp:
            stem = os.path.splitext(outFile)[0]
            files = [stem + e for e in SHP_EXTS if os.path.isfile(stem + e)]
            target = outFile if os.path.isfile(outFile) else stem + '.dbf'
            parts = {'path': target}
        else:
            files = [outFile]
            parts = {'path': outFile, 'layerName': tableName}
        return files, self.relative('ogr', parts)

    # ------------------------------------------------------- project xml
    def loadProject(self):
        f = QFile(self.projectFile)
        if not f.open(QIODevice.OpenModeFlag.ReadOnly):
            raise IOError("Cannot read file %s:\n%s." %
                          (self.projectFile, f.errorString()))
        doc = QDomDocument()
        result = doc.setContent(f, True)
        f.close()
        ok = result[0] if isinstance(result, tuple) else bool(result)
        if not ok:
            raise SyntaxError("Cannot parse project file %s: %s"
                              % (self.projectFile, result))
        return doc

    def saveProject(self, doc):
        f = QFile(self.projectFile)
        if not f.open(QIODevice.OpenModeFlag.WriteOnly |
                      QIODevice.OpenModeFlag.Truncate):
            raise IOError("Cannot write file %s:\n%s." %
                          (self.projectFile, f.errorString()))
        f.write(doc.toByteArray(2))
        f.close()

    @staticmethod
    def _child(doc, parent, tag):
        e = parent.firstChildElement(tag)
        if e.isNull():
            e = doc.createElement(tag)
            parent.appendChild(e)
        return e

    @staticmethod
    def _setText(doc, elem, text):
        while elem.hasChildNodes():
            elem.removeChild(elem.firstChild())
        elem.appendChild(doc.createTextNode(text))

    def makePathsRelative(self, doc, root):
        props = self._child(doc, root, "properties")
        paths = self._child(doc, props, "Paths")
        absolute = self._child(doc, paths, "Absolute")
        absolute.setAttribute("type", "bool")
        self._setText(doc, absolute, "false")
        # a custom "project home" would make relative paths resolve
        # somewhere else
        home = root.firstChildElement("homePath")
        if not home.isNull():
            home.setAttribute("path", "")

    def _setTreeSource(self, doc, layerID, source, provider=None):
        treeNodes = doc.elementsByTagName("layer-tree-layer")
        for i in range(treeNodes.count()):
            e = treeNodes.at(i).toElement()
            if e.attribute("id") == layerID:
                e.setAttribute("source", source)
                if provider:
                    e.setAttribute("providerKey", provider)

    def updateLayer(self, doc, projectLayers, layerID, datasource, provider,
                    encoding):
        node = projectLayers.firstChildElement("maplayer")
        while not node.isNull():
            if node.firstChildElement("id").text() == layerID:
                break
            node = node.nextSiblingElement("maplayer")
        if node.isNull():
            return False
        self._setText(doc, self._child(doc, node, "datasource"), datasource)
        prov = self._child(doc, node, "provider")
        self._setText(doc, prov, provider)
        if encoding:
            prov.setAttribute("encoding", encoding)
        self._setTreeSource(doc, layerID, datasource, provider)
        return True

    def pinUnconsolidated(self, doc, projectLayers):
        node = projectLayers.firstChildElement("maplayer")
        while not node.isNull():
            lid = node.firstChildElement("id").text()
            src = self.keepSources.get(lid)
            ds = node.firstChildElement("datasource")
            if src and not ds.isNull() and \
                    re.match(r'^(file:)?\.', ds.text()):
                self._setText(doc, ds, src)
                self._setTreeSource(doc, lid, src)
            node = node.nextSiblingElement("maplayer")

    # ---------------------------------------------------------------- zip
    def zipfiles(self, filePaths, archive):
        self.checkCanceled()
        archive = "%s.zip" % archive
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED,
                             allowZip64=True) as z:
            seen = set()
            for f in filePaths:
                key = norm(f)
                if key in seen or not os.path.isfile(f):
                    continue
                seen.add(key)
                z.write(f, os.path.relpath(f, self.outputDir))
                self.checkCanceled()
