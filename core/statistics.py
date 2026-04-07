import os
import csv


def generate_stats(coord_csv: str, images_folder: str, output_csv: str):
    """
    Scan images_folder for files named {year}_{pointID}_{direction}.jpg,
    cross-reference with pointIDs from coord_csv, and write a coverage
    matrix CSV: rows = pointID, columns = year, values = image count.
    """
    # Read pointIDs from coordinate CSV
    point_ids = []
    with open(coord_csv, newline='', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            pid = row['pointID']
            if pid not in point_ids:
                point_ids.append(pid)

    # Scan image files
    years = set()
    counts = {}  # (year, str(pointID)) -> int
    for name in os.listdir(images_folder):
        if not name.lower().endswith(('.jpg', '.png', '.jpeg')):
            continue
        parts = name.rsplit('.', 1)[0].split('_')
        if len(parts) != 3:
            continue
        year, pid, _ = parts
        years.add(year)
        key = (year, pid)
        counts[key] = counts.get(key, 0) + 1

    years = sorted(years)

    with open(output_csv, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['pointID'] + years)
        for pid in point_ids:
            row = [pid] + [counts.get((y, str(pid)), 0) for y in years]
            w.writerow(row)
