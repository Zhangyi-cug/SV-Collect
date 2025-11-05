import geopandas as gpd
from shapely.geometry import Point, LineString
import math
from os import path
import time

if __name__ == '__main__':
    filePath = r'sapmple'
    t_start = time.time()


    data = gpd.read_file(path.join(filePath, 'JH.shp'))


    data['FrX'] = None
    data['FrY'] = None
    data['ToX'] = None
    data['ToY'] = None
    data['DIREC'] = None


    for index, row in data.iterrows():
        if index % 100 == 0:
            print(index)
        line = row['geometry']
        start_point = line.coords[0]
        end_point = line.coords[-1]
        start_x, start_y = start_point
        end_x, end_y = end_point
        direction = 180 * math.atan2(end_y - start_y, end_x - start_x) / math.pi


        data.at[index, 'FrX'] = start_x
        data.at[index, 'FrY'] = start_y
        data.at[index, 'ToX'] = end_x
        data.at[index, 'ToY'] = end_y
        data.at[index, 'DIREC'] = direction


    data.to_file(path.join(filePath, 'JH_direction.shp'))

    print("Processing cost {} seconds".format(time.time() - t_start))
