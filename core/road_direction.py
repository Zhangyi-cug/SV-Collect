import math
import os
import shutil
import zipfile
import tempfile

try:
    import shapefile
    HAS_PYSHP = True
except ImportError:
    HAS_PYSHP = False


def process_shapefile(input_shp: str, output_shp: str):
    """
    Read a line shapefile, calculate road direction angle (DIREC) for each
    feature from its start/end points, and write a new shapefile with the
    added fields: StarX, StarY, EndX, EndY, DIREC.

    Requires pyshp (pip install pyshp).
    """
    if not HAS_PYSHP:
        raise ImportError("pyshp is required: pip install pyshp")

    r = shapefile.Reader(input_shp)
    w = shapefile.Writer(output_shp)

    # Copy existing fields (skip deletion flag at index 0)
    w.fields = list(r.fields[1:])
    w.field("StarX", "N", decimal=8)
    w.field("StarY", "N", decimal=8)
    w.field("EndX",  "N", decimal=8)
    w.field("EndY",  "N", decimal=8)
    w.field("DIREC", "N", decimal=6)

    for sr in r.iterShapeRecords():
        pts = sr.shape.points
        if len(pts) < 2:
            w.shape(sr.shape)
            w.record(*sr.record, 0.0, 0.0, 0.0, 0.0, 0.0)
            continue
        x0, y0 = pts[0]
        x1, y1 = pts[-1]
        direc = 180.0 * math.atan2(y1 - y0, x1 - x0) / math.pi
        w.shape(sr.shape)
        w.record(*sr.record, x0, y0, x1, y1, direc)

    w.close()

    # Copy projection file if present
    prj_src = input_shp.replace(".shp", ".prj")
    if os.path.exists(prj_src):
        shutil.copy(prj_src, output_shp.replace(".shp", ".prj"))


def process_to_zip(input_shp: str) -> bytes:
    """
    Process a shapefile and return the result as a zip archive (bytes).
    The zip contains .shp, .shx, .dbf, and optionally .prj.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        out_shp = os.path.join(tmpdir, "output.shp")
        process_shapefile(input_shp, out_shp)

        zip_path = os.path.join(tmpdir, "result.zip")
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for ext in ('.shp', '.shx', '.dbf', '.prj'):
                f = out_shp.replace('.shp', ext)
                if os.path.exists(f):
                    zf.write(f, os.path.basename(f))

        with open(zip_path, 'rb') as f:
            return f.read()
