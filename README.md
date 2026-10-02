# QConsolidate3 (patched fork)

A QGIS plugin that gathers every layer used by the current project into a single folder, writes a new project file that points at those copies using relative paths, and can zip the result. The output can be moved to another folder or computer and opened directly, which makes it suited to handing a project to a colleague or client, or archiving it.

This fork updates QConsolidate3 for QGIS 3.44 LTR and fixes several bugs in the earlier versions, including one that modified source data.

**About this fork:** all code changes from version 0.3.0 onward were written by **Claude, Anthropic's AI assistant (via Claude.ai)**, at the request of Miner-Jeff (GitHub), to make the plugin work with QGIS 3.44 LTR. Claude did the analysis, wrote the code, and ran the automated tests; Miner-Jeff directed the work and carried out limited testing in QGIS 3.44, where it worked as intended.

**Support:** this fork is provided as-is and is not actively maintained. Bug reports and feature requests are not monitored. You are welcome to fork it further under the terms of the license.

> **If you used QConsolidate3 0.2.x or earlier:** when exporting to GeoPackage, those versions deleted any field named `fid` from the **original source layer** and saved the change. If you ran it on Shapefiles, CSVs or other data with a `fid` column, check those originals. This fork never modifies source data.

## Requirements

- QGIS 3.30 or newer (developed for 3.44 LTR; written to also load under Qt6 / QGIS 4)
- No additional Python packages

## Installation

1. Download the plugin ZIP (or zip the `qconsolidate3` folder from this repository).
2. In QGIS, open **Plugins → Manage and Install Plugins → Install from ZIP**.
3. Select the ZIP and click **Install Plugin**, accepting the warning about plugins from outside the official repository.
4. Restart QGIS if you are replacing an older version.

The plugin appears under **Plugins → QConsolidate3** and as an icon on the Plugins toolbar.

## Usage

1. Open the project you want to consolidate. It must be saved to a `.qgs` or `.qgz` file; if it has unsaved changes, the plugin offers to save it first.
2. Run **Plugins → QConsolidate3 → QConsolidate3**.
3. Set:
   - **Project name**: the name of the new project and of its folder.
   - **Output directory**: where that folder is created. It cannot be the folder the current project is in.
   - **Vector layers**: how vector data is handled (see below).
   - **Also create a Zip file**: adds a single zip of the whole result, ready to send.
4. Click **OK**. The job runs in the background (progress in the QGIS task bar). A message at the top of the map reports the result; details on any skipped layers are in **View → Panels → Log Messages**, under the **QConsolidate3** tab.

### Output

```
<project name>/
  <project name>.qgs        project file, relative paths
  <project name>.qgd        auxiliary storage, if the original had any
  layers/                   copied and converted data
  <project name>.zip        only if "Also create a Zip file" was ticked
```

The recipient extracts the zip (fully, not by opening files from inside it) and opens the `.qgs`. The folder can be renamed or moved, but the `.qgs` must stay next to the `layers` folder.

### Vector layer modes

**Keep original formats (copy files)** (default)

- Each source file is copied once, unchanged and under its original name, together with its side-car files. Every layer that uses the file points at the one copy, so a CSV loaded three times with different filters stays one CSV, and a GeoPackage with several project layers stays one GeoPackage.
- Layers that have no file to copy (scratch/memory layers, PostGIS, WFS and other database or web sources) are exported to GeoPackage.
- Layers with unsaved edits are exported to GeoPackage, so the edits are included.
- **Large-file safeguard:** if a file is larger than 100 MB and contains layers the project does not use (for example one layer from a 40-layer GeoPackage or File Geodatabase), only the used layers are exported instead of copying the whole file. The log notes when this happens. The limit can be changed with the setting `qconsolidate3/copy_threshold_mb` (**Settings → Options → Advanced**).
- Files with the same name from different folders are placed in separate sub-folders (`layers/wells_2/wells.gpkg`) instead of overwriting each other.

This is the fastest mode and preserves data exactly. Note that a copied file goes to the recipient complete, including columns or features hidden by a filter in the project.

**Convert all to GeoPackage**

Every vector layer is written to its own GeoPackage, named after the layer. Data is re-encoded to UTF-8. Use this to send only the layers in the project rather than whole source files.

**Convert all to Shapefile**

As above, but Shapefile output, with that format's limits: field names are cut to 10 characters, long text may be truncated, date/time fields lose the time part, and files over 2 GB are not supported. GeoPackage is recommended unless the recipient specifically needs Shapefiles.

When converting:

- Features are exported as the layer currently holds them, including uncommitted edits. Layer filters are kept in the project, not applied to the export.
- Only the layer's own columns are written. Joined fields and virtual (expression) fields are not baked into the file; the joins and expressions remain defined in the project and keep working.
- A source column named `fid` that is not a GeoPackage key is kept as an ordinary column, and the GeoPackage key column is named `fid_pk`.

### Rasters

Local raster files are copied in all modes, with their side-car files (`.tfw`, `.prj`, `.aux.xml`, `.ovr` and so on), once per file even if several layers use them.

### Layers that are not consolidated

These are left pointing at their original source and listed in the log:

- Web and online layers (XYZ tiles, WMS/WMTS, ArcGIS services) and rasters not stored as local files. These keep working wherever there is an internet connection.
- Layer types the plugin does not handle (vector tiles, mesh, point clouds and similar).
- Layers that were already broken (missing source) in the project.

Skipped local layers keep their absolute path, so the recipient will see them as unavailable and can remove or re-point them.

### Not included in the output

- Custom SVG markers, raster images and fonts used in symbology, if they are stored outside the project.
- Plugins the project depends on.

## Credits and license

This plugin has a long lineage:

- **QConsolidate** by Alexander Bruy
- **OQ-Consolidate** by the GEM Foundation
- **QConsolidate3** by Danzig (https://github.com/danzig666/qconsolidate3), including a `.qgz` fix contributed by eanema
- This fork (version 0.3.0 onward): updated for QGIS 3.44 LTR by Claude (Anthropic's AI assistant, via Claude.ai) at the request of Miner-Jeff (GitHub); see [CHANGELOG.md](CHANGELOG.md)

Released under the GNU Affero General Public License v3, which provides the software without any warranty. See [LICENSE](LICENSE).
