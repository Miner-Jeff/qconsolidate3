# Changelog

All notable changes in this fork. Versions up to 0.2.1 are the original QConsolidate3 by Danzig.

Versions 0.3.0 and 0.4.0 were produced by **Claude, Anthropic's AI assistant (via Claude.ai)**, at the request of Miner-Jeff (GitHub), with the goal of making the plugin work with **QGIS 3.44 LTR**. Claude reviewed the existing code, identified the problems, wrote all of the changes listed below, and tested them in automated, headless runs against QGIS 3.34 on Python 3.12 (the same Python version as QGIS 3.44). Miner-Jeff requested and directed the changes and carried out limited testing of the plugin in QGIS 3.44, where it worked as intended.

## [0.4.0]

Changes written by Claude (Anthropic, via Claude.ai) at the request of Miner-Jeff (GitHub).

### Added
- **Keep original formats (copy files)** mode, now the default. Source files are copied unchanged with their side-car files, once per file, and every layer using a file points at the single copy.
- In that mode, layers without a file (memory, PostGIS, WFS and similar) are exported to GeoPackage.
- In that mode, layers with unsaved edits are exported to GeoPackage so the edits are included.
- Large-file safeguard: a file over 100 MB that contains layers the project does not use is not copied whole; only the used layers are exported. Configurable through the `qconsolidate3/copy_threshold_mb` setting.
- File Geodatabase (`.gdb` folder) sources can be copied.
- The finish message reports how many layers were copied and how many converted, and log notes explain any safeguard or unsaved-edit exports.

### Changed
- The format option is now **Vector layers** with three choices: Keep original formats, Convert all to GeoPackage, Convert all to Shapefile. The previous choice from 0.3.0 is carried over.
- Rasters are copied once per source file instead of once per layer, keeping original file names.
- All data source paths are written through QGIS's own relative-path handling, which also covers CSV and raster-in-GeoPackage sources.
- Minimum QGIS version raised to 3.30.

### Fixed
- Files with the same name from different folders no longer overwrite each other; later ones go into their own sub-folder.
- Exporting a layer whose name starts with `gpkg`, `sqlite_` or `rtree_` to GeoPackage failed, because those table name prefixes are reserved. The table is now given a `layer_` prefix; the file keeps the layer's name.
- Recent edits held in a GeoPackage's `-wal` file are included when the file is copied.

## [0.3.0]

Changes written by Claude (Anthropic, via Claude.ai) at the request of Miner-Jeff (GitHub), to make the plugin work with QGIS 3.44 LTR.

### Fixed
- **Source data is no longer modified.** Earlier versions deleted fields named `fid` from the original layer when exporting to GeoPackage. A non-GeoPackage `fid` column is now kept as an ordinary column and the GeoPackage key is named `fid_pk`.
- About dialog crashed on Python 3.12 (QGIS 3.40 and later) because `configparser.SafeConfigParser` was removed.
- Crash when the project had layers added since it was last saved. The plugin now offers to save the project first and requires a saved `.qgs` or `.qgz`.
- A single invalid or unsupported layer (vector tiles, mesh, point cloud, ...) aborted the whole consolidation. Such layers are now skipped with a warning.
- Skipped layers with local sources were re-pointed at non-existent paths in the new folder when the project switched to relative paths. They now keep their absolute original path.
- Raster side-car files (`.tfw`, `.prj`, `.aux.xml`, `.ovr`, ...) were not copied.
- Raster sources with extra URI parts (for example rasters inside a GeoPackage, NetCDF variables) were copied incorrectly.
- A custom project home path made the relative paths in the new project resolve to the wrong place; it is now cleared.
- Layer tree entries in the project file kept the old source paths.
- For `.qgz` projects, the auxiliary storage file (`.qgd`) was not renamed with the project.
- The output folder could be the same as the source project's folder.

### Changed
- Project layers are read only on the main thread; the background task works from thread-safe feature sources, avoiding crashes in recent QGIS versions.
- Joined fields and virtual (expression) fields are no longer written into exported files; they remain defined in the project.
- GeoPackage is the default output format; the last used settings are remembered.
- Qt6-compatible enum usage and no compiled PyQt5 resource file, so the plugin can load under QGIS 4.
- Marked as non-experimental.

## [0.2.1] and earlier

Original QConsolidate3 by Danzig. See https://github.com/danzig666/qconsolidate3.
